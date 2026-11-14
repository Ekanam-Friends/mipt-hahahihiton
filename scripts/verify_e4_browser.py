"""Real Chrome smoke test; replay of E3 is explicitly separated from live search.

python scripts/verify_e4_browser.py --url http://127.0.0.1:8014
Requires optional development dependency: playwright (uses installed Chrome).
"""
import argparse
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8014')
    parser.add_argument('--output', default='data/official/e4-browser')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    urls, errors, checks = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True, args=['--no-proxy-server'])
        context = browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True)
        page = context.new_page()
        context.on('request', lambda request: urls.append(request.url))
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url, wait_until='domcontentloaded', timeout=60000)
        page.get_by_role('button', name='Сотрудник ·').click()
        page.get_by_role('button', name='ИИ-ассистент', exact=True).click()
        page.locator('#question').fill('Как открыть финансовый лицевой счёт?')
        page.locator('#submit').click()
        page.wait_for_selector('#conversation article')
        assert page.locator('#conversation .badge').inner_text() == 'Частичный ответ'
        page.locator('#conversation details summary').first.click()
        with page.expect_popup() as popup:
            page.get_by_role('link', name='Точный фрагмент').first.click()
        popup.value.wait_for_load_state()
        assert popup.value.url.split('#')[-1]
        assert popup.value.locator('[id="' + popup.value.url.split('#')[-1] + '"]').count() == 1
        popup.value.close()
        with page.expect_download() as download:
            page.get_by_role('link', name='Скачать оригинал').first.click()
        assert download.value.suggested_filename
        checks.append('live extractive answer, exact fragment, original download')
        page.screenshot(path=str(output / 'desktop.png'), full_page=True)

        # Render a saved, source-reviewed E3 response, not a new LLM generation.
        report = json.loads(Path('data/official/e3-current-extra-report.json').read_text(encoding='utf-8'))
        saved = next(row['answer'] for row in report['results'] if row['answer']['steps'])
        def adapt(value):
            if isinstance(value, dict):
                if value.get('doc_id'):
                    root = '/api/documents/' + quote(value['doc_id'], safe='')
                    fragment = value.get('chunk_id', '').partition('#')[2]
                    value.update(view_url=root+'/view#'+quote(fragment, safe=''), download_url=root+'/original')
                for child in list(value.values()):
                    adapt(child)
            elif isinstance(value, list):
                for child in value:
                    adapt(child)
        adapt(saved)
        submitted = []
        def replay(route):
            submitted.append(route.request.post_data_json)
            route.fulfill(json=saved)
        page.route('**/api/ask', replay)
        page.locator('#question').fill('Покажи полный порядок')
        page.locator('#submit').click()
        page.locator('#conversation article').nth(1).wait_for()
        assert page.locator('#conversation article').first.get_by_role('heading', name='Порядок действий').count() == 1
        assert submitted[-1]['history']
        checks.append('saved E3 procedure renders steps; history sent on follow-up')
        page.screenshot(path=str(output / 'procedure-replay.png'), full_page=True)
        page.unroute('**/api/ask')
        page.route('**/api/ask', lambda route: route.fulfill(status=503, json={'status':'error', 'message':'Сервис модели недоступен. Повторите запрос.'}))
        page.locator('#question').fill('Повторяемый вопрос')
        page.locator('#submit').click()
        page.locator('#conversation article').nth(2).wait_for()
        assert page.locator('#question').input_value() == 'Повторяемый вопрос'
        assert page.locator('#submit').is_enabled()
        page.unroute('**/api/ask')
        checks.append('provider error retains input and enables retry (HTTP response simulated)')
        page.locator('#reset').click()
        assert page.locator('#conversation article').count() == 0
        page.get_by_role('button', name='Выйти', exact=True).click()
        page.get_by_role('button', name='Преподаватель ·').click()
        page.get_by_role('button', name='ИИ-ассистент', exact=True).click()
        page.set_viewport_size({'width':360, 'height':800})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(output / 'mobile.png'), full_page=True)
        checks.append('reset, logout, teacher login, 360px without horizontal overflow')
        assert not errors, errors
        assert all(urlsplit(url).netloc == urlsplit(args.url).netloc for url in urls), urls
        browser.close()
    result = {'checks':checks, 'page_errors':errors, 'request_urls':sorted(set(urls)),
              'note':'Live extractive search and real source links; E3 procedure and 503 rendering replayed, not new inference.'}
    (output / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
