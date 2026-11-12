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


class LLMClient(Protocol):
    def complete(self, system: str, user: str, *, temperature: float = 0.0) -> str: ...


class OpenAICompatClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        self.base_url = (base_url or os.environ["OPENAI_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "EMPTY")
        self.model = model or os.environ.get("OPENAI_MODEL", "ai-sage/GigaChat-20B-A3B-instruct")
        self.http = httpx.Client(timeout=120)

    def complete(self, system: str, user: str, *, temperature: float = 0.0) -> str:
        r = self.http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class GigaChatClient:
    OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    API = "https://gigachat.devices.sberbank.ru/api/v1"

    def __init__(self, auth_key: str | None = None, scope: str | None = None, model: str | None = None):
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

    def complete(self, system: str, user: str, *, temperature: float = 0.0) -> str:
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
    if kind == "gigachat":
        return GigaChatClient()
    if kind == "openai":
        return OpenAICompatClient()
    return None
