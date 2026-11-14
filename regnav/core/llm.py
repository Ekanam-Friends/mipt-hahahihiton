"""Адаптеры LLM и эмбеддингов. Провайдер выбирается переменной REGNAV_LLM.

- extractive  — без LLM (по умолчанию): шаги собираются из найденных пунктов дословно.
- gigachat    — GigaChat API (ключ авторизации GIGACHAT_AUTH_KEY).
- openai      — любой OpenAI-совместимый сервер: vLLM с GigaChat-20B-A3B-instruct внутри
                контура, YandexGPT (OpenAI-совместимый эндпоинт) и т.д.
                OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL.

ВНИМАНИЕ: клиенты gigachat/openai написаны по документации и ещё не проверены на живом
ключе — проверить, как только появятся ключи.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Protocol

import httpx
import numpy as np
from .privacy import check_provider, local_only
from .budget import remaining_timeout


class LLMClient(Protocol):
    def complete(self, system: str, user: str, *, temperature: float = 0.0, response_schema: dict | None = None) -> str: ...


class OpenAICompatClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        self.base_url = (base_url or os.environ["OPENAI_BASE_URL"]).rstrip("/")
        check_provider('openai', self.base_url)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "EMPTY")
        self.model = model or os.environ.get("OPENAI_MODEL", "ai-sage/GigaChat-20B-A3B-instruct")
        self.http = httpx.Client(timeout=float(os.environ.get("REGNAV_LLM_TIMEOUT", "600")),
                                 trust_env=not local_only(), follow_redirects=False)

    def complete(self, system: str, user: str, *, temperature: float = 0.0, response_schema: dict | None = None) -> str:
        r = self.http.post(
            f"{self.base_url}/chat/completions",
            timeout=remaining_timeout(float(os.environ.get('REGNAV_LLM_TIMEOUT', '600'))),
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": temperature,
                "max_tokens": int(os.environ.get("REGNAV_MAX_TOKENS", "1800")),
                **({"response_format": {"type": "json_schema", "json_schema": {
                    "name": "regnav", "strict": True, "schema": response_schema}}} if response_schema else {}),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class GigaChatClient:
    OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    API = "https://gigachat.devices.sberbank.ru/api/v1"

    def __init__(self, auth_key: str | None = None, scope: str | None = None, model: str | None = None):
        check_provider('gigachat')
        self.auth_key = auth_key or os.environ["GIGACHAT_AUTH_KEY"]
        self.scope = scope or os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
        self.model = model or os.environ.get("GIGACHAT_MODEL", "GigaChat")
        # Сертификат НУЦ Минцифры: путь к нему в GIGACHAT_CA_BUNDLE, иначе системные.
        verify = os.environ.get("GIGACHAT_CA_BUNDLE", True)
        self.http = httpx.Client(timeout=120, verify=verify)
        self._token, self._exp = "", 0.0

    def _auth(self) -> str:
        if time.time() < self._exp - 60:
            return self._token
        r = self.http.post(
            self.OAUTH,
            headers={"Authorization": f"Basic {self.auth_key}", "RqUID": str(uuid.uuid4())},
            data={"scope": self.scope},
        )
        r.raise_for_status()
        j = r.json()
        self._token, self._exp = j["access_token"], j["expires_at"] / 1000
        return self._token

    def complete(self, system: str, user: str, *, temperature: float = 0.0, response_schema: dict | None = None) -> str:
        r = self.http.post(
            f"{self.API}/chat/completions",
            headers={"Authorization": f"Bearer {self._auth()}"},
            json={
                "model": self.model,
                "temperature": max(temperature, 0.01),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def embed(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 64):
            r = self.http.post(
                f"{self.API}/embeddings",
                headers={"Authorization": f"Bearer {self._auth()}"},
                json={"model": "Embeddings", "input": texts[i : i + 64]},
            )
            r.raise_for_status()
            out.extend(d["embedding"] for d in r.json()["data"])
        return np.array(out, dtype=np.float32)


def client_from_env() -> LLMClient | None:
    kind = os.environ.get("REGNAV_LLM", "extractive").lower()
    check_provider(kind, os.environ.get('OPENAI_BASE_URL'))
    if kind == "gigachat":
        return GigaChatClient()
    if kind == "openai":
        return OpenAICompatClient()
    return None
