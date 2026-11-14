"""Disconnect-safe jobs, session privacy, bounded queue, provider time budget."""
import threading
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from regnav.core.budget import question_budget, remaining_timeout
from regnav.core.llm import OpenAICompatClient
from regnav.web.app import create_app
from test_web import Stub, corpus


def payload(q='question'):
    return {'question': q, 'request_id': str(uuid.uuid4())}


def login(client):
    client.cookies.clear()
    assert client.post('/api/demo/login', json={'user_id': 'employee-demo'}).status_code == 200


def test_jobs_survive_disconnect_deduplicate_and_isolate_sessions(tmp_path):
    release = threading.Event()
    calls = []
    class Slow(Stub):
        def ask(self, *args, **kwargs):
            calls.append(args[0])
            release.wait(3)
            return super().ask(*args, **kwargs)
    try:
        with TestClient(create_app(corpus(tmp_path), lambda _: Slow())) as client:
            login(client)
            first_cookie = client.cookies.get('regnav_session')
            body = payload()
            response = client.post('/api/jobs', json=body)
            assert response.status_code == 202
            jid = response.json()['job_id']
            assert client.post('/api/jobs', json=body).json()['job_id'] == jid
            assert client.post('/api/jobs', json={**body, 'question': 'different'}).status_code == 409
            assert client.post('/api/jobs', json=payload()).status_code == 429
            assert client.get('/api/jobs/'+jid).json()['state'] in {'queued', 'running'}
            login(client)  # Same demo profile, different session: no access to prior question.
            assert client.get('/api/jobs/'+jid).status_code == 404
            second = client.post('/api/jobs', json=payload('second')).json()['job_id']
            assert client.get('/api/jobs/'+second).json()['state'] == 'queued'
            release.set()
            for _ in range(100):
                if client.get('/api/jobs/'+second).json()['state'] == 'done':
                    break
                time.sleep(.01)
            assert client.get('/api/jobs/'+second).json()['result']['status'] == 'partial'
            client.cookies.clear()
            client.cookies.set('regnav_session', first_cookie)
            assert client.get('/api/jobs/'+jid).json()['result']['question'] == 'question'
            assert calls == ['question', 'second']
    finally:
        release.set()


def test_provider_calls_share_budget_and_stop_after_deadline(monkeypatch):
    client = OpenAICompatClient('http://127.0.0.1:8087/v1')
    limits = []
    def reply(request):
        limits.append(request.extensions['timeout']['read'])
        return httpx.Response(200, json={'choices': [{'message': {'content': '{}'}}]})
    client.http.close()
    client.http = httpx.Client(transport=httpx.MockTransport(reply))
    with question_budget(.2):
        client.complete('system', 'user')
        time.sleep(.03)
        client.complete('system', 'user')
        assert 0 < limits[1] < limits[0] <= .201
    with question_budget(-1):
        with pytest.raises(TimeoutError):
            client.complete('system', 'user')
    assert len(limits) == 2
    client.http.close()


def test_job_timeout_is_technical_error_not_absent_information(tmp_path):
    class Slow(Stub):
        def ask(self, *args, **kwargs):
            time.sleep(.03)
            return super().ask(*args, **kwargs)
    with TestClient(create_app(corpus(tmp_path), lambda _: Slow(), timeout=.01)) as client:
        login(client)
        jid = client.post('/api/jobs', json=payload()).json()['job_id']
        for _ in range(100):
            result = client.get('/api/jobs/'+jid).json()
            if result['state'] == 'done':
                break
            time.sleep(.01)
        assert result['result']['error_code'] == 'timeout'
        assert result['result']['status'] == 'error'


def test_repeated_question_uses_cache_but_date_and_history_do_not(tmp_path):
    nav = Stub()
    with TestClient(create_app(corpus(tmp_path), lambda _: nav)) as client:
        login(client)
        def ask(body):
            jid = client.post('/api/jobs', json=body).json()['job_id']
            for _ in range(100):
                job = client.get('/api/jobs/'+jid).json()
                if job['state'] == 'done':
                    return job['result']
                time.sleep(.01)
            raise AssertionError('Job did not complete')
        assert not ask({**payload(), 'as_of': '2026-11-14'}).get('cache_hit')
        assert ask({**payload(), 'as_of': '2026-11-14'})['cache_hit']
        assert not ask({**payload(), 'as_of': '2026-11-15'}).get('cache_hit')
        assert not ask({**payload(), 'as_of': '2026-11-14', 'history': ['prior']}).get('cache_hit')
