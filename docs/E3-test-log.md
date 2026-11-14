# Журнал проверок E3

Снимок журнала: 13.11.2026 15:34 МСК.

Это реестр доказательств, а не автоматическая приёмка. `answer`, попадание цитаты и самооценка модели не означают успешную смысловую сверку. Для текущего кода применимы только совпадающие хеши; завершённость наборов и рецензии проверяются отдельно.

## Зарегистрированные unit-прогоны

Флаг снимка относится ко всему охвату конкретного запуска. Его нестабильность из-за независимых файлов E4 не отменяет успешные тесты E3. В прогоне 99 тестов неизменность поднабора E3 подтверждена отдельным [разбором охвата](../data/official/e3-unit-scope-credit-report.json); затем 94 теста E3 повторно прошли со стабильными хешами.

| Отчёт | Exit code pytest / runner | Стабильный снимок / исходный флаг регистратора | Файлы охвата совпадают с текущими | Вывод |
|---|---|---|---|---|
| [20261112T235727075749Z.json](../data/official/e3-unit-runs/20261112T235727075749Z.json) | 0 / None | True / True | False | 81 passed in 4.58s |
| [20261113T000339747280Z.json](../data/official/e3-unit-runs/20261113T000339747280Z.json) | 1 / None | True / False | False | 2 failed, 83 passed in 2.50s |
| [20261113T000427767272Z.json](../data/official/e3-unit-runs/20261113T000427767272Z.json) | 0 / None | True / True | False | 85 passed in 1.64s |
| [20261113T001841367951Z.json](../data/official/e3-unit-runs/20261113T001841367951Z.json) | 0 / None | True / True | False | 86 passed in 4.87s |
| [20261113T002042359377Z.json](../data/official/e3-unit-runs/20261113T002042359377Z.json) | 0 / None | True / True | False | 87 passed in 2.66s |
| [20261113T002614278204Z.json](../data/official/e3-unit-runs/20261113T002614278204Z.json) | 0 / None | True / True | False | 87 passed in 3.01s |
| [20261113T003540802150Z.json](../data/official/e3-unit-runs/20261113T003540802150Z.json) | 1 / None | True / False | False | 1 failed, 86 passed in 3.05s |
| [20261113T003613555404Z.json](../data/official/e3-unit-runs/20261113T003613555404Z.json) | 0 / None | True / True | False | 90 passed in 1.99s |
| [20261113T003649537675Z.json](../data/official/e3-unit-runs/20261113T003649537675Z.json) | 1 / None | True / False | False | 9 failed, 81 passed in 1.83s |
| [20261113T003706627549Z.json](../data/official/e3-unit-runs/20261113T003706627549Z.json) | 0 / None | True / True | False | 90 passed in 1.54s |
| [20261113T013104104743Z.json](../data/official/e3-unit-runs/20261113T013104104743Z.json) | 0 / None | True / True | False | 91 passed in 16.10s |
| [20261113T014601937571Z.json](../data/official/e3-unit-runs/20261113T014601937571Z.json) | 0 / None | False / False | False | 94 passed in 23.82s |
| [20261113T014844256227Z.json](../data/official/e3-unit-runs/20261113T014844256227Z.json) | 0 / 2 | False / False | False | 99 passed, 1 warning in 324.82s (0:05:24) |
| [20261113T015711007903Z.json](../data/official/e3-unit-runs/20261113T015711007903Z.json) | 0 / 0 | True / True | False | 94 passed in 9.80s |
| [20261113T120541511999Z.json](../data/official/e3-unit-runs/20261113T120541511999Z.json) | 0 / 0 | True / True | True | 95 passed in 3.43s |

## Ранее наблюдавшиеся unit-прогоны

Ниже — сводки из выводов инструментов этого чата до введения файлового регистратора. Точные время запуска и хеш кода для них не восстанавливаются и не приписываются задним числом. Они документируют ход исправлений, но не удостоверяют текущую версию.

| Этап | Наблюдавшийся результат |
|---|---|
| Исходное состояние | 67 passed in 2.54s |
| OCR и привязка приёмки | 69 passed in 3.28s |
| Нумерованный список внутри пункта | 70 passed in 2.60s |
| Явный диапазон процедуры | 71 passed in 3.16s |
| Обоснованность not_found | 72 passed in 2.48s |
| Раздельные части и страницы фрагментов | 75 passed in 2.25s |
| Промежуточная ошибка инициализации режима | 25 failed, 51 passed in 3.42s; исправлена перед следующим прогоном |
| Выбор целых пунктов после исправления | 76 passed in 2.19s |
| Обязательная полнота диапазона | 77 passed in 1.79s |
| Переход на проверку частей: старые заглушки | 2 failed, 75 passed in 2.88s; обновлён протокол заглушек |
| Проверка изоляции частей | 1 failed, 78 passed in 2.09s; исправлен повтор предшествующего вопроса |
| Раздельная проверка частей | 79 passed in 1.94s |
| Краткий ответ до перестановки шагов | 79 passed in 1.68s |
| Несовпадение явно названного листа | 81 passed in 10.90s |

## Сохранённые модельные и вспомогательные проверки

| Отчёт | Ответов | Статусы | Сверка источников | Код совпадает | Флаг проверки / приёмки |
|---|---:|---|---|---|---|
| [e3-acceptance-report.json](../data/official/e3-acceptance-report.json) | 0 | {} | {} | True | True |
| [e3-adversarial-report.json](../data/official/e3-adversarial-report.json) | 1 | {'answer': 1} | {'not_recorded': 1} | None | True |
| [e3-answer-report.json](../data/official/e3-answer-report.json) | 26 | {'answer': 9, 'error': 17} | {'pending': 26} | False | False |
| [e3-audit-shape-baseline-report.json](../data/official/e3-audit-shape-baseline-report.json) | 1 | {'error': 1} | {'pending': 1} | False | False |
| [e3-baseline-report.json](../data/official/e3-baseline-report.json) | 2 | {'error': 2} | {'not_recorded': 2} | None | False |
| [e3-before-borrowing-question-fix-report.json](../data/official/e3-before-borrowing-question-fix-report.json) | 20 | {'answer': 16, 'clarify': 3, 'error': 1} | {'pending': 20} | False | False |
| [e3-before-city-abbreviation-fix-report.json](../data/official/e3-before-city-abbreviation-fix-report.json) | 24 | {'answer': 20, 'clarify': 3, 'error': 1} | {'pending': 24} | False | False |
| [e3-before-clause-answer-report.json](../data/official/e3-before-clause-answer-report.json) | 1 | {'answer': 1} | {'pending': 1} | False | False |
| [e3-before-composite-isolation-report.json](../data/official/e3-before-composite-isolation-report.json) | 6 | {'answer': 5, 'clarify': 1} | {'pending': 6} | False | False |
| [e3-before-fact-relevance-report.json](../data/official/e3-before-fact-relevance-report.json) | 8 | {'answer': 8} | {'pending': 6, 'rejected': 2} | False | False |
| [e3-before-parser-report.json](../data/official/e3-before-parser-report.json) | 1 | {'answer': 1} | {'pending': 1} | False | False |
| [e3-before-relevance-answer-report.json](../data/official/e3-before-relevance-answer-report.json) | 1 | {'answer': 1} | {'pending': 1} | False | False |
| [e3-before-relevance-report.json](../data/official/e3-before-relevance-report.json) | 5 | {'not_found': 2, 'partial': 1, 'answer': 2} | {'pending': 5} | False | False |
| [e3-compact-pilot-report.json](../data/official/e3-compact-pilot-report.json) | 3 | {'partial': 3} | {'pending': 3} | False | False |
| [e3-context-report.json](../data/official/e3-context-report.json) | 0 | {} | {} | False | None |
| [e3-current-adversarial-report.json](../data/official/e3-current-adversarial-report.json) | 1 | {'answer': 1} | {'not_recorded': 1} | True | True |
| [e3-current-answer-report.json](../data/official/e3-current-answer-report.json) | 26 | {'answer': 23, 'clarify': 3} | {'accepted': 26} | True | True |
| [e3-current-extra-report.json](../data/official/e3-current-extra-report.json) | 7 | {'not_found': 2, 'partial': 1, 'answer': 4} | {'accepted': 7} | True | True |
| [e3-evidence-progress.json](../data/official/e3-evidence-progress.json) | 0 | {} | {} | None | True |
| [e3-evidence-report.json](../data/official/e3-evidence-report.json) | 0 | {} | {} | None | True |
| [e3-extra-evidence-progress.json](../data/official/e3-extra-evidence-progress.json) | 0 | {} | {} | None | True |
| [e3-extra-postprocessing-check-report.json](../data/official/e3-extra-postprocessing-check-report.json) | 0 | {} | {} | None | True |
| [e3-final-extra-replayed-report.json](../data/official/e3-final-extra-replayed-report.json) | 4 | {'answer': 2, 'not_found': 1, 'error': 1} | {'pending': 4} | False | False |
| [e3-final-extra-report.json](../data/official/e3-final-extra-report.json) | 1 | {'answer': 1} | {'pending': 1} | False | False |
| [e3-final-replayed-report.json](../data/official/e3-final-replayed-report.json) | 1 | {'answer': 1} | {'pending': 1} | False | False |
| [e3-final-report.json](../data/official/e3-final-report.json) | 1 | {'answer': 1} | {'pending': 1} | False | False |
| [e3-isolation-only-failed-report.json](../data/official/e3-isolation-only-failed-report.json) | 5 | {'answer': 4, 'clarify': 1} | {'pending': 5} | False | False |
| [e3-main-before-final-audit-report.json](../data/official/e3-main-before-final-audit-report.json) | 14 | {'answer': 10, 'clarify': 3, 'partial': 1} | {'pending': 14} | False | False |
| [e3-metadata-scope-check-report.json](../data/official/e3-metadata-scope-check-report.json) | 0 | {} | {} | None | True |
| [e3-metadata-scope-inference-report.json](../data/official/e3-metadata-scope-inference-report.json) | 6 | {'answer': 5, 'clarify': 1} | {'pending': 6} | False | False |
| [e3-paraphrase-baseline-report.json](../data/official/e3-paraphrase-baseline-report.json) | 2 | {'answer': 2} | {'rejected': 1, 'pending': 1} | False | False |
| [e3-pilot-report.json](../data/official/e3-pilot-report.json) | 2 | {'error': 2} | {'not_recorded': 2} | None | False |
| [e3-procedure-inference-report.json](../data/official/e3-procedure-inference-report.json) | 7 | {'not_found': 2, 'answer': 4, 'partial': 1} | {'pending': 7} | False | False |
| [e3-qwen17-partial-run-report.json](../data/official/e3-qwen17-partial-run-report.json) | 7 | {'answer': 7} | {'pending': 5, 'rejected': 2} | False | False |
| [e3-qwen4-partial-run-report.json](../data/official/e3-qwen4-partial-run-report.json) | 2 | {'answer': 2} | {'accepted': 1, 'pending': 1} | False | False |
| [e3-qwen4-pilot-report.json](../data/official/e3-qwen4-pilot-report.json) | 1 | {'not_found': 1} | {'pending': 1} | False | False |
| [e3-rejected-procedure-baseline-report.json](../data/official/e3-rejected-procedure-baseline-report.json) | 6 | {'not_found': 2, 'partial': 1, 'answer': 3} | {'pending': 4, 'rejected': 2} | False | False |
| [e3-relevance-pilot-report.json](../data/official/e3-relevance-pilot-report.json) | 0 | {} | {} | None | 7/7 диагностики |
| [e3-replay-order-failed-report.json](../data/official/e3-replay-order-failed-report.json) | 2 | {'not_found': 2} | {'accepted': 2} | False | False |
| [e3-retry-report.json](../data/official/e3-retry-report.json) | 1 | {'answer': 1} | {'pending': 1} | False | False |
| [e3-run-events.json](../data/official/e3-run-events.json) | 0 | {} | {} | None | None |
| [e3-scoped-progress-report.json](../data/official/e3-scoped-progress-report.json) | 6 | {'answer': 5, 'clarify': 1} | {'pending': 6} | False | False |
| [e3-simple-pilot-report.json](../data/official/e3-simple-pilot-report.json) | 2 | {'answer': 2} | {'pending': 2} | False | False |
| [e3-structured-baseline-report.json](../data/official/e3-structured-baseline-report.json) | 1 | {'error': 1} | {'pending': 1} | False | False |
| [e3-unit-scope-credit-report.json](../data/official/e3-unit-scope-credit-report.json) | 0 | {} | {} | None | True |
| [e3-wide-context-baseline-report.json](../data/official/e3-wide-context-baseline-report.json) | 2 | {'error': 1, 'partial': 1} | {'pending': 2} | False | False |

## Текущие контрольные сценарии

Длительность включает все вызовы и возможное ожидание общего сервера; это не изолированный замер скорости. Replay повторяет сохранённые ответы модели только при побайтовом совпадении запросов; режим указан явно. «Сверено в реестре» означает совпадение хеша ответа с отдельной рецензией Codex; применение рецензий к итоговому отчёту выполняется после завершения сбора.

| Набор / ID | Статус | Сверка | Вызовов | Секунд исходного прогона | Режим |
|---|---|---|---:|---:|---|
| e3-current-answer-report.json / fls-composite | answer | accepted | 9 | 377.7 | replay |
| e3-current-answer-report.json / travel | answer | accepted | 8 | 143.51 | replay |
| e3-current-answer-report.json / form-2019 | clarify | accepted | 3 | 73.95 | replay |
| e3-current-answer-report.json / long-composite | answer | accepted | 9 | 669.65 | replay |
| e3-current-answer-report.json / estimate-composite | answer | accepted | 5 | 522.34 | replay |
| e3-current-answer-report.json / structure | answer | accepted | 5 | 1077.27 | replay |
| e3-current-answer-report.json / fls-conflict | clarify | accepted | 5 | 392.64 | replay |
| e3-current-answer-report.json / fls-open | answer | accepted | 3 | 269.42 | replay |
| e3-current-answer-report.json / fls-number | clarify | accepted | 5 | 509.04 | replay |
| e3-current-answer-report.json / fls-edition | answer | accepted | 3 | 431.38 | replay |
| e3-current-answer-report.json / fls-old | answer | accepted | 3 | 362.9 | replay |
| e3-current-answer-report.json / estimate-forms | answer | accepted | 5 | 728.6 | replay |
| e3-current-answer-report.json / estimate-start | answer | accepted | 3 | 237.08 | replay |
| e3-current-answer-report.json / travel-paraphrase | answer | accepted | 6 | 282.03 | replay |
| e3-current-answer-report.json / budget | answer | accepted | 3 | 134.39 | replay |
| e3-current-answer-report.json / eb | answer | accepted | 3 | 113.84 | replay |
| e3-current-answer-report.json / support | answer | accepted | 3 | 104.47 | replay |
| e3-current-answer-report.json / hall | answer | accepted | 5 | 131.72 | replay |
| e3-current-answer-report.json / personnel | answer | accepted | 4 | 136.95 | replay |
| e3-current-answer-report.json / borrowing | answer | accepted | 5 | 216.94 | replay |
| e3-current-answer-report.json / datacenter | answer | accepted | 4 | 110.78 | replay |
| e3-current-answer-report.json / form-rcni | answer | accepted | 3 | 106.33 | replay |
| e3-current-answer-report.json / housing | answer | accepted | 3 | 251.61 | live |
| e3-current-answer-report.json / form-docx | answer | accepted | 3 | 496.04 | live |
| e3-current-answer-report.json / structure-xlsx | answer | accepted | 3 | 175.09 | live |
| e3-current-answer-report.json / budget-appendix | answer | accepted | 4 | 344.91 | live |
| e3-current-extra-report.json / negative-mortgage | not_found | accepted | 0 | 0.03 | replay |
| e3-current-extra-report.json / negative-secret | not_found | accepted | 2 | 57.14 | replay |
| e3-current-extra-report.json / partial-support-mortgage | partial | accepted | 13 | 362.83 | replay |
| e3-current-extra-report.json / procedure-datacenter | answer | accepted | 14 | 1855.6 | replay |
| e3-current-extra-report.json / procedure-support-datacenter | answer | accepted | 51 | 1011.49 | replay |
| e3-current-extra-report.json / procedure-recruitment | answer | accepted | 2 | 180.13 | replay |
| e3-current-extra-report.json / procedure-fls-3065 | answer | accepted | 2 | 431.81 | replay |

## Смысловая сверка и оригиналы

- [Методика и найденные дефекты](E3.md).
- [Рецензии Codex с хешами конкретных ответов](../eval/e3-final-source-reviews.json).
- [Поиск E2](../data/official/e2-search-report.json) и [проверка импорта E1](../data/official/e1-validation.json).
- Оригиналы PDF визуально сверяются по страницам; Office проверены также независимым чтением XML/ячеек в E1. Изображения находятся в `data/official/evidence/e3-review-*.png`.
- Рецензии Codex не являются приёмкой человеком или владельцем регламентов.

Обновление: `python scripts/document_e3_tests.py`. Новый unit-прогон с полным stdout и хешами: `python scripts/run_e3_tests.py`.
