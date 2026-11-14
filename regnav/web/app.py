"""Run: python -m uvicorn regnav.web.app:app --host 127.0.0.1 --port 8000."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date
import logging
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from regnav.__main__ import make_navigator
from regnav.core.ingest import load_manifest, source_path
from .accounts import Accounts

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=8000)
    history: list[str] = Field(default_factory=list, max_length=6)
    as_of: date | None = None

    @field_validator("history")
    @classmethod
    def bounded_history(cls, value):
        if any(not item.strip() or len(item) > 8000 for item in value):
            raise ValueError("Некорректная история")
        return value


class DemoLogin(BaseModel):
    user_id: str = Field(max_length=100)


def failure(code, message, status=503):
    return JSONResponse({"status": "error", "error_code": code, "message": message}, status_code=status)


def create_app(data_dir: Path | None = None, navigator_factory=make_navigator, timeout: float | None = None,
               db_path: Path | None = None):
    data = (data_dir or Path(os.environ.get("REGNAV_DATA", "data/official"))).resolve()
    deadline = timeout if timeout is not None else float(os.environ.get("REGNAV_WEB_TIMEOUT", "1800"))
    if deadline <= 0:
        raise ValueError("REGNAV_WEB_TIMEOUT must be positive")

    @asynccontextmanager
    async def lifespan(app):
        app.state.accounts = Accounts(db_path or Path(os.environ.get("REGNAV_WEB_DB", str(data / "web" / "accounts.sqlite3"))))
        app.state.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="regnav-web")
        app.state.pending = None
        app.state.navigator = None
        app.state.records = {}
        try:
            app.state.navigator = navigator_factory(data)
            records = load_manifest(data)
            app.state.records = {r["id"]: r for r in records}
        except Exception:
            log.exception("Cannot load corpus")
            app.state.navigator = None
        yield
        app.state.pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Навигатор регламентов", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware('http')
    async def authentication(request: Request, call_next):
        if request.headers.get('content-length', '').isdigit() and int(request.headers['content-length']) > 262144:
            return failure('request_too_large', 'Запрос слишком большой. Сократите вопрос и историю.', 413)
        if request.method in {'POST', 'PUT', 'DELETE', 'PATCH'}:
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return failure('invalid_origin', 'Запрос с другого сайта отклонён.', 403)
        public = {'/api/health', '/api/demo/accounts', '/api/demo/login'}
        if request.url.path.startswith('/api/') and request.url.path not in public:
            request.state.profile = app.state.accounts.current(request.cookies.get('regnav_session'))
            if request.state.profile is None:
                return failure('unauthorized', 'Войдите в демонстрационный кабинет.', 401)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        if request.url.path == '/':
            response.headers['Content-Security-Policy'] = "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.get('/api/demo/accounts')
    def demo_accounts():
        return app.state.accounts.profiles()

    @app.post('/api/demo/login')
    def demo_login(payload: DemoLogin, request: Request):
        token = app.state.accounts.login(payload.user_id)
        if token is None:
            return failure('unknown_account', 'Демонстрационный аккаунт не найден.', 404)
        app.state.accounts.logout(request.cookies.get('regnav_session'))
        response = JSONResponse({'status': 'ok'})
        response.set_cookie('regnav_session', token, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', max_age=8 * 3600)
        return response

    @app.post('/api/logout')
    def logout(request: Request):
        app.state.accounts.logout(request.cookies.get('regnav_session'))
        response = JSONResponse({'status': 'ok'})
        response.delete_cookie('regnav_session')
        return response

    @app.get('/api/me')
    def me(request: Request):
        return request.state.profile

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return failure("invalid_request", "Введите вопрос от 1 до 8000 символов; история — до 6 реплик. Дата: YYYY-MM-DD.", 422)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    def health():
        ready = app.state.navigator is not None and bool(app.state.navigator.searcher.chunks)
        return JSONResponse({"status": "ready" if ready else "unavailable"}, status_code=200 if ready else 503)

    def adapt(answer):
        # Keep E3 fields intact, adding browser links from known document IDs only.
        result = answer.to_dict()
        def visit(value):
            if isinstance(value, dict):
                did = value.get("doc_id")
                if did in app.state.records:
                    root = "/api/documents/" + quote(did, safe="")
                    fragment = value.get("chunk_id", "").partition("#")[2]
                    if not fragment:
                        fragment = (value.get("view_path") or "").partition("#")[2]
                    value["view_url"] = root + "/view" + ("#" + quote(fragment, safe="") if fragment else "")
                    value["download_url"] = root + "/original"
                for child in list(value.values()):
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(result)
        # Internal audit failures can contain provider details. Expose a code only.
        if result.get("status") == "error":
            result["verification"] = {}
        return result

    @app.post("/api/ask")
    async def ask(payload: AskRequest):
        if app.state.navigator is None:
            return failure("index_unavailable", "База недоступна. Проверьте импорт и перезапустите сервис.")
        if app.state.pending is not None and not app.state.pending.done():
            return failure("busy", "Предыдущий запрос ещё обрабатывается. Повторите позже.", 429)
        future = app.state.pool.submit(app.state.navigator.ask, payload.question, history=payload.history,
                                       as_of=payload.as_of.isoformat() if payload.as_of else None)
        app.state.pending = future
        try:
            answer = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), deadline)
            result = adapt(answer)
            return JSONResponse(result, status_code=503 if result.get('status') == 'error' else 200)
        except asyncio.TimeoutError:
            # A Python thread cannot be killed safely. Retain the busy slot until it finishes.
            return failure("timeout", "Время ожидания истекло. Обработка завершается; повторите позже.", 504)
        except Exception:
            log.exception("Question processing failed")
            return failure("request_failed", "Не удалось обработать вопрос. Повторите запрос.")

    def document(doc_id):
        record = app.state.records.get(doc_id)
        if record is None:
            raise HTTPException(404, "Документ не найден")
        return record

    @app.get("/api/documents/{doc_id}/view")
    def view(doc_id: str):
        document(doc_id)
        path = (data / "view" / f"{doc_id}.html").resolve()
        if not path.is_relative_to(data / "view") or not path.is_file():
            raise HTTPException(404, "Просмотр недоступен; выполните импорт")
        return FileResponse(path, media_type="text/html", headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/documents/{doc_id}/original")
    def original(doc_id: str):
        record = document(doc_id)
        path = source_path(record, data).resolve()
        if not path.is_relative_to(data) or not path.is_file():
            raise HTTPException(404, "Оригинал недоступен в каталоге корпуса")
        return FileResponse(path, filename=record.get("original_name") or path.name,
                            media_type="application/octet-stream")

    return app


app = create_app()
