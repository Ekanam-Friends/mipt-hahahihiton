"""Inventory E3 evidence without treating model flags as quality acceptance."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/official'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    current = {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in (ROOT / 'regnav/core').glob('*.py')}
    review_path = ROOT / 'eval/e3-final-source-reviews.json'
    ledger = json.loads(review_path.read_text(encoding='utf-8')).get('reviews', {}) if review_path.exists() else {}
    reports = []
    for path in sorted(DATA.glob('e3-*.json')):
        if path.name in {'e3-test-inventory.json', 'e3-unit-observations.json'}:
            continue
        raw = path.read_bytes()
        row = {'path': str(path.relative_to(ROOT)), 'sha256': digest(raw),
               'file_modified_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}
        try:
            report = json.loads(raw)
            results = report.get('results', [])
            results = results if isinstance(results, list) else []
            answers = [r for r in results if isinstance(r, dict) and isinstance(r.get('answer'), dict)]
            if isinstance(report.get('answer'), dict):
                answers.append({'answer': report['answer']})
            row.update(created_at=report.get('created_at'), recorded=len(answers),
                       statuses=dict(Counter(r['answer'].get('status', 'unknown') for r in answers)),
                       source_reviews=dict(Counter(r.get('source_review', {}).get('state', 'not_recorded') for r in answers)),
                       quality_acceptance=report.get('quality_acceptance'), check_passed=report.get('passed'),
                       implementation_matches=(report['implementation_sha256'] == current
                                               if 'implementation_sha256' in report else None))
            if results and all(isinstance(r, dict) and 'actual' in r and 'expected' in r for r in results):
                row['diagnostic_matches'] = sum(r['actual'] == r['expected'] for r in results)
                row['diagnostic_total'] = len(results)
        except (ValueError, AttributeError):
            row['read_error'] = 'invalid JSON or a report still being written; no result inferred'
        reports.append(row)
    unit_runs = []
    for path in sorted((DATA / 'e3-unit-runs').glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        matches = all((ROOT / name).is_file() and digest((ROOT / name).read_bytes()) == value
                      for name, value in record['files_sha256'].items())
        unit_runs.append({'path': str(path.relative_to(ROOT)), 'finished_at': record['finished_at'],
                          'returncode': record['returncode'], 'passed': record['passed'],
                          'runner_returncode': record.get('runner_returncode'), 'snapshot_stable': record['snapshot_stable'],
                          'matches_current_files': matches, 'stdout': record['stdout']})
    historical_path = DATA / 'e3-unit-observations.json'
    historical = json.loads(historical_path.read_text(encoding='utf-8')) if historical_path.exists() else {}
    now = datetime.now(timezone.utc)
    output = {'generated_at': now.isoformat(), 'scope': 'Evidence inventory, not automatic semantic acceptance',
              'reports': reports, 'unit_runs': unit_runs, 'historical_unit_observations': historical}
    (DATA / 'e3-test-inventory.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# Журнал проверок E3', '', 'Снимок журнала: ' + now.astimezone(timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M МСК') + '.', '',
             'Это реестр доказательств, а не автоматическая приёмка. `answer`, попадание цитаты и самооценка модели не означают успешную смысловую сверку. Для текущего кода применимы только совпадающие хеши; завершённость наборов и рецензии проверяются отдельно.', '',
             '## Зарегистрированные unit-прогоны', '',
             'Флаг снимка относится ко всему охвату конкретного запуска. Его нестабильность из-за независимых файлов E4 не отменяет успешные тесты E3. В прогоне 99 тестов неизменность поднабора E3 подтверждена отдельным [разбором охвата](../data/official/e3-unit-scope-credit-report.json); затем 94 теста E3 повторно прошли со стабильными хешами.', '',
             '| Отчёт | Exit code pytest / runner | Стабильный снимок / исходный флаг регистратора | Файлы охвата совпадают с текущими | Вывод |', '|---|---|---|---|---|']
    for run in unit_runs:
        summary = run['stdout'].strip().splitlines()[-1] if run['stdout'].strip() else 'нет stdout'
        lines.append(f"| [{Path(run['path']).name}](../{run['path'].replace(chr(92), '/')}) | {run['returncode']} / {run['runner_returncode']} | {run['snapshot_stable']} / {run['passed']} | {run['matches_current_files']} | {summary} |")
    lines += ['', '## Ранее наблюдавшиеся unit-прогоны', '',
              'Ниже — сводки из выводов инструментов этого чата до введения файлового регистратора. Точные время запуска и хеш кода для них не восстанавливаются и не приписываются задним числом. Они документируют ход исправлений, но не удостоверяют текущую версию.', '',
              '| Этап | Наблюдавшийся результат |', '|---|---|']
    for run in historical.get('observations', []):
        lines.append(f"| {run['stage']} | {run['result']} |")
    lines += ['', '## Сохранённые модельные и вспомогательные проверки', '',
              '| Отчёт | Ответов | Статусы | Сверка источников | Код совпадает | Флаг проверки / приёмки |', '|---|---:|---|---|---|---|']
    for report in reports:
        name = Path(report['path']).name
        flag = report.get('check_passed') if report.get('check_passed') is not None else report.get('quality_acceptance')
        if 'diagnostic_total' in report:
            flag = f"{report['diagnostic_matches']}/{report['diagnostic_total']} диагностики"
        lines.append(f"| [{name}](../{report['path'].replace(chr(92), '/')}) | {report.get('recorded', '—')} | {report.get('statuses', report.get('read_error', '—'))} | {report.get('source_reviews', '—')} | {report.get('implementation_matches', False)} | {flag} |")
    lines += ['', '## Текущие контрольные сценарии', '',
              'Длительность включает все вызовы и возможное ожидание общего сервера; это не изолированный замер скорости. Replay повторяет сохранённые ответы модели только при побайтовом совпадении запросов; режим указан явно. «Сверено в реестре» означает совпадение хеша ответа с отдельной рецензией Codex; применение рецензий к итоговому отчёту выполняется после завершения сбора.', '',
              '| Набор / ID | Статус | Сверка | Вызовов | Секунд исходного прогона | Режим |',
              '|---|---|---|---:|---:|---|']
    for filename in ('e3-current-answer-report.json', 'e3-current-extra-report.json'):
        path = DATA / filename
        if not path.exists():
            continue
        try:
            report = json.loads(path.read_text(encoding='utf-8'))
        except ValueError:
            continue
        for row in report.get('results', []):
            review_state = row.get('source_review', {}).get('state', 'pending')
            review = ledger.get(row['id'], {})
            answer_hash = digest(json.dumps(row['answer'], ensure_ascii=False, sort_keys=True).encode('utf-8'))
            if review_state == 'pending' and review.get('answer_sha256') == answer_hash:
                review_state = 'сверено в реестре' if all(review['checks'].values()) else 'отклонено в реестре'
            lines.append(f"| {filename} / {row['id']} | {row['answer']['status']} | {review_state} | {len(row.get('calls', []))} | {row.get('elapsed_s')} | {row.get('inference_mode', 'not_recorded')} |")
    lines += ['', '## Смысловая сверка и оригиналы', '',
              '- [Методика и найденные дефекты](E3.md).',
              '- [Рецензии Codex с хешами конкретных ответов](../eval/e3-final-source-reviews.json).',
              '- [Поиск E2](../data/official/e2-search-report.json) и [проверка импорта E1](../data/official/e1-validation.json).',
              '- Оригиналы PDF визуально сверяются по страницам; Office проверены также независимым чтением XML/ячеек в E1. Изображения находятся в `data/official/evidence/e3-review-*.png`.',
              '- Рецензии Codex не являются приёмкой человеком или владельцем регламентов.', '',
              'Обновление: `python scripts/document_e3_tests.py`. Новый unit-прогон с полным stdout и хешами: `python scripts/run_e3_tests.py`.', '']
    (ROOT / 'docs/E3-test-log.md').write_text('\n'.join(lines), encoding='utf-8')
    print('Inventoried reports:', len(reports), 'registered unit runs:', len(unit_runs))


if __name__ == '__main__':
    main()
