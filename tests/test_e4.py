"""E4 privacy boundaries, real corpus over HTTP and provider failure."""
import json
from pathlib import Path
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from regnav.core.llm import OpenAICompatClient, client_from_env
from regnav.web.app import create_app


@pytest.mark.parametrize('provider,url', [
    ('openai', 'https://api.example.invalid/v1'),
    ('openai', 'http://localhost.example.invalid/v1'),
    ('openai', 'http://user:password@127.0.0.1/v1'),
    ('gigachat', ''), ('typo', ''),
])
def test_local_mode_rejects_external_before_network(monkeypatch, provider, url):
    monkeypatch.setenv('REGNAV_LOCAL_ONLY', '1')
    monkeypatch.setenv('REGNAV_LLM', provider)
    monkeypatch.setenv('OPENAI_BASE_URL', url)
    with pytest.raises(ValueError):
        client_from_env()


def test_local_client_ignores_proxy_and_redirect(monkeypatch):
    monkeypatch.setenv('REGNAV_LOCAL_ONLY', '1')
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy.example.invalid:8080')
    client = OpenAICompatClient('http://127.0.0.1:8087/v1')
    assert client.http.trust_env is False
    assert client.http.follow_redirects is False
    client.http.close()


def test_official_http_without_outbound_connections(tmp_path, monkeypatch):
    if not Path('data/official/chunks.jsonl').exists():
        pytest.skip('Import the official corpus first')
    attempts = []
    def blocked(sock, address):
        attempts.append(str(address))
        raise AssertionError('Unexpected outbound connection')
    monkeypatch.setenv('REGNAV_LLM', 'extractive')
    monkeypatch.setenv('REGNAV_LOCAL_ONLY', '1')
    questions = [
        'Как открыть финансовый лицевой счёт?',
        'Как открыть финансовый лицевой счёт и оформить внутреннее заимствование?',
        'Расскажите о порядке открытия финансового лицевого счёта. ' * 120,
        'Как получить ипотеку на личную квартиру через Госуслуги?',
    ]
    with TestClient(create_app(Path('data/official'), db_path=tmp_path / 'accounts.sqlite3')) as client:
        # Windows creates a loopback socketpair when starting the ASGI event loop.
        # Begin the network audit after that framework setup, before any request.
        monkeypatch.setattr(socket.socket, 'connect', blocked)
        monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
        assert client.post('/api/demo/login', json={'user_id': 'employee-demo'}).status_code == 200
        document_ids = set()
        for question in questions:
            response = client.post('/api/ask', json={'question': question})
            assert response.status_code == 200
            body = response.json()
            assert body['status'] in {'partial', 'not_found', 'clarify'}
            for claim in body['summary']:
                for item in claim['evidence']:
                    document_ids.add(item['doc_id'])
                    html = client.get(item['view_url'])
                    assert html.status_code == 200
                    anchor = item['view_url'].partition('#')[2]
                    assert f'id="{anchor}"' in html.text
                    assert client.get(item['download_url']).status_code == 200
        assert len(document_ids) >= 2
        assert body['status'] == 'not_found'
        assert client.post('/api/ask', json={'question': 'x' * 8001}).status_code == 422
        assert client.get('/api/me').headers['cache-control'] == 'no-store'
    assert attempts == []


def test_real_local_provider_failure_is_safe_and_retryable(tmp_path, monkeypatch):
    if not Path('data/official/chunks.jsonl').exists():
        pytest.skip('Import the official corpus first')
    requests = []
    class Unavailable(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'private provider diagnostic')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Unavailable)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('REGNAV_LLM', 'openai')
    monkeypatch.setenv('REGNAV_LOCAL_ONLY', '1')
    monkeypatch.setenv('OPENAI_BASE_URL', f'http://127.0.0.1:{server.server_port}/v1')
    try:
        with TestClient(create_app(Path('data/official'), db_path=tmp_path / 'accounts.sqlite3')) as client:
            client.post('/api/demo/login', json={'user_id': 'employee-demo'})
            for _ in range(2):
                response = client.post('/api/ask', json={'question': 'Как открыть финансовый лицевой счёт?'})
                assert response.status_code == 503
                assert response.json()['status'] == 'error'
                assert 'private provider diagnostic' not in response.text
        assert len(requests) == 2
        assert all('messages' in body for body in requests)
        assert all('Марина' not in json.dumps(body, ensure_ascii=False) for body in requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
