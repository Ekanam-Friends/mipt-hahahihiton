"""Smoke test against a running web service, with real HTTP and source downloads."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8016')
    parser.add_argument('--output', default='data/official/e4-checks/live.json')
    args = parser.parse_args()
    observations = []
    with httpx.Client(base_url=args.url, trust_env=False, timeout=120) as client:
        assert client.get('/api/health').status_code == 200
        assert client.post('/api/demo/login', json={'user_id':'employee-demo'}).status_code == 200
        assert client.get('/api/me').json()['role'] == 'employee'
        for question in [
            'Как открыть финансовый лицевой счёт?',
            'Как открыть финансовый лицевой счёт и оформить внутреннее заимствование?',
            'Расскажите о порядке открытия финансового лицевого счёта. ' * 120,
            'Как получить ипотеку на личную квартиру через Госуслуги?',
        ]:
            started = time.monotonic()
            response = client.post('/api/ask', json={'question':question})
            assert response.status_code == 200, response.text
            body = response.json()
            ids = set()
            for claim in body['summary']:
                for item in claim['evidence']:
                    ids.add(item['doc_id'])
                    view = client.get(item['view_url'])
                    anchor = item['view_url'].partition('#')[2]
                    assert view.status_code == 200 and f'id="{anchor}"' in view.text
                    assert client.get(item['download_url']).status_code == 200
            observations.append({'question':question[:180], 'characters':len(question), 'status':body['status'],
                                 'document_ids':sorted(ids), 'elapsed_s':round(time.monotonic()-started,3)})
        assert observations[-1]['status'] == 'not_found'
        assert len(observations[1]['document_ids']) >= 2
        for question in ['', ' ', 'x'*8001]:
            assert client.post('/api/ask', json={'question':question}).status_code == 422
        assert client.post('/api/logout').status_code == 200
        assert client.get('/api/me').status_code == 401
    result = {'created_at':datetime.now(timezone.utc).isoformat(), 'url':args.url,
              'mode':'extractive; no new LLM generations', 'observations':observations,
              'checks':['health','login','source anchors and original downloads','multi-document','long input',
                        'negative','invalid input','logout']}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
