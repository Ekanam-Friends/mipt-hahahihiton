"""HTTP boundaries tested without calling the model or modifying E3 fixtures."""
import json
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient as BaseClient

from regnav.core.grounding import Claim, Evidence
from regnav.core.pipeline import Answer
from regnav.web.app import create_app


class TestClient(BaseClient):
    __test__ = False

    def __enter__(self):
        super().__enter__()
        assert self.post('/api/demo/login', json={'user_id': 'employee-demo'}).status_code == 200
        return self


def corpus(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "view").mkdir()
    (tmp_path / "raw" / "doc.pdf").write_bytes(b"original")
    (tmp_path / "view" / "doc.html").write_text('<p id="p1">Source</p>')
    (tmp_path / "manifest.jsonl").write_text(json.dumps({"id": "doc", "title": "Document", "local_path": "raw/doc.pdf"}) + '\n')
    return tmp_path


class Stub:
    searcher = SimpleNamespace(chunks=[1])

    def ask(self, question, history, as_of):
        self.received = (question, history, as_of)
        return Answer("partial", question, summary=[Claim("Finding", [Evidence("doc#p1", "Exact quote", "doc", "Document", "Section 1")])])


def test_answer_history_sources_and_validation(tmp_path):
    nav = Stub()
    with TestClient(create_app(corpus(tmp_path), lambda _: nav)) as client:
        assert client.get('/api/health').json()['status'] == 'ready'
        assert client.get('/').status_code == 200
        response = client.post('/api/ask', json={'question': ' Follow up ', 'history': ['Prior question'], 'as_of': '2026-11-13'})
        assert response.status_code == 200
        assert nav.received == ('Follow up', ['Prior question'], '2026-11-13')
        e = response.json()['summary'][0]['evidence'][0]
        assert e['view_url'] == '/api/documents/doc/view#p1'
        assert client.get(e['view_url']).status_code == 200
        assert client.get(e['download_url']).content == b'original'
        for body in ({'question': ' '}, {'question': 'x' * 8001}, {'question': 'q', 'history': ['x'] * 7}, {'question': 'q', 'as_of': 'yesterday'}):
            result = client.post('/api/ask', json=body)
            assert result.status_code == 422
            assert result.json()['error_code'] == 'invalid_request'
        assert client.get('/api/documents/unknown/original').status_code == 404


def test_timeout_retains_busy_slot(tmp_path):
    release, started = threading.Event(), threading.Event()
    class Slow(Stub):
        def ask(self, *args, **kwargs):
            started.set()
            release.wait(5)
            return Answer('not_found', 'q')
    try:
        with TestClient(create_app(corpus(tmp_path), lambda _: Slow(), timeout=.03)) as client:
            assert client.post('/api/ask', json={'question': 'q'}).status_code == 504
            assert started.is_set()
            assert client.post('/api/ask', json={'question': 'q'}).status_code == 429
    finally:
        release.set()


def test_safe_failure_and_missing_index(tmp_path):
    class Broken(Stub):
        def ask(self, *args, **kwargs):
            raise RuntimeError('secret provider detail')
    data = corpus(tmp_path)
    with TestClient(create_app(data, lambda _: Broken())) as client:
        response = client.post('/api/ask', json={'question': 'q'})
        assert response.status_code == 503
        assert 'secret' not in response.text
    def unavailable(_):
        raise FileNotFoundError('private path')
    with TestClient(create_app(data, unavailable)) as client:
        assert client.get('/api/health').status_code == 503
        assert client.post('/api/ask', json={'question': 'q'}).json()['error_code'] == 'index_unavailable'


def test_original_cannot_escape_corpus(tmp_path):
    data = corpus(tmp_path)
    record = {'id': 'outside', 'local_path': str(tmp_path.parent / 'private.pdf')}
    (data / 'manifest.jsonl').write_text(json.dumps(record) + '\n')
    with TestClient(create_app(data, lambda _: Stub())) as client:
        assert client.get('/api/documents/outside/original').status_code == 404


def test_official_offline_answer(tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setenv('REGNAV_LLM', 'extractive')
    import pytest
    if not Path('data/official/chunks.jsonl').exists():
        pytest.skip('Official corpus is not imported')
    with TestClient(create_app(Path('data/official'), db_path=tmp_path / 'accounts.sqlite3')) as client:
        result = client.post('/api/ask', json={'question': 'Как открыть финансовый лицевой счёт?'})
        assert result.status_code == 200
        body = result.json()
        assert body['status'] == 'partial'
        assert body['summary'] and body['missing_information']
        for claim in body['summary']:
            for item in claim['evidence']:
                assert client.get(item['view_url']).status_code == 200
                assert client.get(item['download_url']).status_code == 200


def test_sessions_roles_logout_and_origin(tmp_path):
    data = corpus(tmp_path)
    with BaseClient(create_app(data, lambda _: Stub())) as client:
        assert client.get('/api/me').status_code == 401
        assert client.post('/api/ask', json={'question': 'q'}).status_code == 401
        assert client.get('/api/documents/doc/original').status_code == 401
        assert client.post('/api/demo/login', json={'user_id': 'unknown'}).status_code == 404
        result = client.post('/api/demo/login', json={'user_id': 'teacher-demo'})
        assert 'HttpOnly' in result.headers['set-cookie']
        assert client.get('/api/me').json()['role'] == 'teacher'
        assert client.get('/api/me?user_id=employee-demo').json()['id'] == 'teacher-demo'
        assert client.post('/api/logout', headers={'Origin': 'https://other.example'}).status_code == 403
        token = client.cookies.get('regnav_session')
        assert client.post('/api/logout').status_code == 200
        client.cookies.set('regnav_session', token)
        assert client.get('/api/me').status_code == 401
