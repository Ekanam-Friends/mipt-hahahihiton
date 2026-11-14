import copy
import hashlib
import json

import pytest

from regnav.core.ingest import corrected_extraction
from scripts.apply_e3_reviews import validate_snapshot
from regnav.core.parse import split_document
from regnav.core.parse import Chunk
from regnav.core.pipeline import Navigator
from regnav.core.search import Hit, HybridSearcher
from regnav.core.grounding import source_units


def test_procedural_clause_keeps_action_and_maximum_term_together():
    text = 'Доступ предоставляется на основании заявки через 1С:ДО. Максимальный срок составляет один год.'
    units, _, context = source_units([Hit(Chunk('x', 'd', 'Регламент', '4.1', '', text), 1, 1, {})], whole_clauses=True)
    assert units == {'c1s0': (text, 'c1')}
    assert context[0]['units'] == [{'id': 'c1s0', 'text': text}]


def test_explicit_full_range_cannot_pass_with_a_missing_point_even_if_model_would_approve():
    from regnav.core.pipeline import LLMReasoner
    from regnav.core.grounding import GenerationError
    class Client:
        def complete(self, system, user, **kwargs):
            assert kwargs['response_schema']['properties']['unit_ids']['minItems'] == 2
            return json.dumps({'unit_ids': ['c1s0']})
    hits = [Hit(Chunk(str(i), 'd', 'Регламент', f'3.{i}', '',
                      'Работник заполняет все обязательные поля заявки.'), 1, 1, {}) for i in (1, 2)]
    with pytest.raises(GenerationError, match='Неполный явно заданный диапазон'):
        LLMReasoner(Client()).checklist('Дай полный порядок по пунктам 3.1–3.2.', hits)


def test_explicit_procedure_range_loads_requested_section_even_if_search_ranks_another_first():
    chunks = [Chunk('wrong', 'doc', 'Регламент', '3.2', '', 'Другой маршрут ГОСТ РВ.'),
              *[Chunk(str(i), 'doc', 'Регламент', f'2.{i}', '', f'Действие номер {i}.') for i in range(1, 10)],
              Chunk('date', 'doc', 'Регламент', '1', '', 'Дата начала действия.')]
    nav = Navigator(HybridSearcher(chunks), None)
    hits = [Hit(chunks[0], 1, 1, {}), Hit(chunks[1], 1, 1, {}), Hit(chunks[-1], 1, 1, {'applicability': 1})]
    result = nav._procedure_context('Дай полный порядок по пунктам 2.1–2.9, не ГОСТ РВ.', hits, [])
    assert [h.chunk.chunk_id for h in result] == [*[str(i) for i in range(1, 10)], 'date']


def test_numbered_list_does_not_swallow_following_procedure_or_its_page():
    chunks = split_document(['2. Определения\n2.1. Варианты работы:\n1) первый\n2) второй\n3) третий\n4) четвертый',
                             '3. ПОРЯДОК\n3.1. Руководитель заполняет заявку.\n3.2. Директор согласует заявку.'], 'doc', 'Регламент')
    assert [c.clause for c in chunks] == ['2', '2.1', '3', '3.1', '3.2']
    assert '4) четвертый' in chunks[1].text
    assert chunks[-2].page == 2 and chunks[-1].page == 2


def test_approved_regulation_resets_order_numbering_on_next_page():
    chunks = split_document(['3. Изменить пункт приказа.\n4. Утвердить регламент.\n5. Контроль.',
                             'УТВЕРЖДЕН\n1. Общие положения\nОпределения.',
                             '2. Порядок\n2.1. Сотрудник присваивает номер.'], 'd', 'Приказ')
    point = next(c for c in chunks if c.clause.endswith('2.1'))
    assert point.page == 3 and 'Сотрудник присваивает номер' in point.text


def test_long_point_fragment_links_to_actual_page_not_the_start_of_the_point():
    first = 'Первое предложение на первой странице. ' * 40
    second = 'Совершенно другое действие на следующей странице. ' * 40
    chunks = split_document(['1. Порядок\n1.1. ' + first, second], 'd', 'Регламент')
    fragments = [c for c in chunks if '1.1' in c.clause]
    assert any(c.page == 2 and c.text.startswith('Совершенно') for c in fragments)


def test_reviewed_ocr_repair_is_page_and_hash_bound_and_does_not_modify_cache(tmp_path):
    raw = {'sha256': 'original', 'blocks': [{'page': 1, 'text': '7 лёт'},
                                         {'page': 2, 'text': 'не более 7 лёт'}]}
    saved = copy.deepcopy(raw)
    repair = {'source_sha256': 'original', 'page': 2, 'before': '7 лёт', 'after': '7 лет'}
    (tmp_path / 'ocr-corrections.json').write_text(json.dumps({'doc': [repair]}), encoding='utf-8')
    fixed = corrected_extraction(raw, 'doc', tmp_path)
    assert raw == saved
    assert fixed['blocks'] == [{'page': 1, 'text': '7 лёт'}, {'page': 2, 'text': 'не более 7 лет'}]
    raw['sha256'] = 'changed'
    with pytest.raises(ValueError, match='another source snapshot'):
        corrected_extraction(raw, 'doc', tmp_path)
    raw['sha256'] = 'original'
    raw['blocks'][1]['text'] = '7 лет'
    assert corrected_extraction(raw, 'doc', tmp_path)['corrections'][0]['state'] == 'already_correct'
    raw['blocks'][1]['text'] = '7 дней'
    with pytest.raises(ValueError, match='no longer matches'):
        corrected_extraction(raw, 'doc', tmp_path)
    raw['blocks'][1]['text'] = '7 лет и 7 лет'
    with pytest.raises(ValueError, match='no longer matches'):
        corrected_extraction(raw, 'doc', tmp_path)


def test_acceptance_rejects_stale_code_and_index(tmp_path):
    core = tmp_path / 'regnav/core'
    core.mkdir(parents=True)
    code = core / 'pipeline.py'
    code.write_text('original')
    index = tmp_path / 'chunks.jsonl'
    index.write_text('original')
    digest = hashlib.sha256(b'original').hexdigest()
    report = {'implementation_sha256': {str(code.relative_to(tmp_path)): digest},
              'corpus_sha256': {'chunks.jsonl': digest}}
    validate_snapshot(report, tmp_path)
    index.write_text('changed')
    with pytest.raises(ValueError, match='Snapshot changed'):
        validate_snapshot(report, tmp_path)
    index.write_text('original')
    (core / 'search.py').write_text('new dependency')
    with pytest.raises(ValueError, match='Incomplete implementation'):
        validate_snapshot(report, tmp_path)


def test_absent_fact_audit_distinguishes_justified_refusal_from_complete_answer():
    from regnav.core.pipeline import LLMReasoner
    class Client:
        def complete(self, system, user, **kwargs):
            if 'независимый проверяющий' not in user:
                return json.dumps({'unit_ids': []})
            assert 'отсутствие запрошенных сведений как раз обосновывает not_found' in user
            return json.dumps({'summary_supported': {}, 'steps_supported': {}, 'complete': False,
                               'ordered': True, 'status_supported': True,
                               'missing_information': ['В источнике нет запрошенных сведений.'], 'conflicts': []})
    nav = Navigator(HybridSearcher([Chunk('x', 'd', 'ЦОД', '1', '',
                                         'Обслуживание сервера ЦОД выполняет подразделение УИТ.')]), LLMReasoner(Client()), min_top_coverage=0)
    result = nav.ask('Какой пароль сервера ЦОД?')
    assert result.status == 'not_found' and not result.steps and not result.summary


def test_open_procedure_rejects_untyped_relevance_instead_of_accepting_provider_string():
    from regnav.core.pipeline import LLMReasoner
    class Client:
        def complete(self, *args, **kwargs):
            return json.dumps({'relevant': 'true'})
    nav = Navigator(HybridSearcher([Chunk('x', 'd', 'Регламент', '4.1', '',
                                         'Заявка на сервер подаётся через 1С:ДО.')]), LLMReasoner(Client()), min_top_coverage=0)
    answer = nav.ask('Как подать заявку на сервер?')
    assert answer.status == 'error' and answer.error_code == 'invalid_generation'


def test_independent_procedures_are_audited_as_separate_questions_with_all_context():
    from regnav.core.pipeline import LLMReasoner
    class Client:
        def __init__(self):
            self.checked = []

        def complete(self, system, user, **kwargs):
            if user.startswith('Проверь прямую применимость'):
                data = json.loads(user.split('\nДанные:\n', 1)[1])
                text, question = data['candidate']['text'], data['question']
                return json.dumps({'relevant': ('сервер' in question and text.startswith('Заявка')) or
                                              ('поддержк' in question and text.startswith('Официальный'))})
            assert 'независимый проверяющий' in user
            question = json.loads(user.split('Проверяй только этот вопрос сотрудника:\n', 1)[1])
            self.checked.append(question)
            assert not ('сервер' in question and 'поддержк' in question)
            # Every audit still sees BOTH source documents, not just its selected proof.
            assert 'Заявка на сервер' in user and 'Официальный канал поддержки' in user
            return json.dumps({'summary_supported': {'0': True}, 'steps_supported': {'0': {
                'action': True, 'responsible': True, 'deadline': True, 'documents': {}}},
                'complete': True, 'ordered': True, 'status_supported': True,
                'missing_information': [], 'conflicts': []})
    chunks = [Chunk('a', 'server', 'ЦОД', '4.1', '', 'Заявка на сервер подаётся через 1С:ДО. Максимальный срок — один год.'),
              Chunk('b', 'help', 'Поддержка', '2.1', '', 'Официальный канал поддержки — helpdesk@example.test.'),
              Chunk('heading', 'server', 'ЦОД', '4', '', 'Порядок предоставления сервисов')]
    client = Client()
    answer = Navigator(HybridSearcher(chunks), LLMReasoner(client), min_top_coverage=0).ask(
        'Как подать заявку на сервер? Как обратиться в поддержку?')
    assert answer.status == 'answer' and len(answer.steps) == 2 and len(client.checked) == 2
    assert 'один год' in answer.steps[0].action
    assert {source['doc_id'] for source in answer.sources} == {'server', 'help'}


@pytest.mark.parametrize('requested,status', [('смета_универсальная', 'clarify'), ('смет_поквартально', 'answer')])
def test_named_worksheet_cannot_be_silently_substituted(requested, status):
    from regnav.core.pipeline import LLMReasoner
    class Client:
        def complete(self, system, user, **kwargs):
            if 'Проверь уместность' in user:
                return json.dumps({'relevant': True})
            if 'независимый проверяющий' not in user:
                return json.dumps({'unit_ids': ['c1s0']})
            return json.dumps({'summary_supported': {'0': True}, 'steps_supported': {},
                               'complete': True, 'ordered': True, 'status_supported': True,
                               'missing_information': [], 'conflicts': []})
    chunk = Chunk('cell', 'book', 'Смета 2019', "'смет_поквартально'!I1:I1", '',
                  'Лист «смет_поквартально», I1:I1: I1: Приложение № 1а', meta={'sheet': 'смет_поквартально'})
    nav = Navigator(HybridSearcher([chunk]), LLMReasoner(Client()), min_top_coverage=0)
    answer = nav.ask('Приложение 1а на листе ' + requested)
    assert answer.status == status
    assert answer.summary[0].evidence[0].chunk_id == 'cell'
    if status == 'clarify':
        assert requested in answer.clarifying_question and 'смет_поквартально' in answer.clarifying_question
        assert answer.verification['requested_locator_supported'] is False


def test_start_date_context_keeps_the_explicit_order_even_if_another_edition_ranks_first():
    old = Chunk('old', 'old', '460-1 Открытие ФЛС', '4', '', 'Ввести регламент в действие с 1 мая 2017 года.')
    new = Chunk('new', 'new', 'Приказ N 3065-1', '1', '', 'Утвердить новую редакцию с 1 декабря 2021 года.')
    nav = Navigator(HybridSearcher([old, new]), None)
    hits = [Hit(new, 1, 1, {'applicability': 1}), Hit(old, 1, 1, {})]
    trace = [{'query': 'дата', 'chunk_ids': ['new', 'old'], 'status': 'found'}]
    kept = nav._generation_context('С какого числа вводится регламент по приказу 460-1?', hits, trace)
    assert {hit.chunk.chunk_id for hit in kept} == {'old'}


def test_factual_relevance_removes_number_definition_from_who_question():
    from regnav.core.pipeline import LLMReasoner
    class Search:
        chunks = [Chunk('actor', 'd', 'Порядок', '2.2', '', 'Номер ФЛС присваивает сотрудник ФЭУ по данным карточки проекта.'),
                  Chunk('width', 'd', 'Порядок', '2.3', '', 'Номер ФЛС состоит из 11–18 разрядов.')]

        def retrieve(self, *args):
            return [('номер', [Hit(c, 1, 1, {}) for c in self.chunks])]

    class Client:
        def complete(self, system, user, **kwargs):
            if 'Проверь уместность ОДНОГО выбранного предложения' in user:
                data = json.loads(user.split('\nКандидат:\n', 1)[1])
                return json.dumps({'relevant': data['candidate']['id'] == 'c1s0'})
            if 'независимый проверяющий' in user:
                return json.dumps({'summary_supported': {'0': True}, 'steps_supported': {}, 'complete': True,
                                   'ordered': True, 'status_supported': True, 'missing_information': [], 'conflicts': []})
            return json.dumps({'unit_ids': ['c1s0', 'c2s0']})
    answer = Navigator(Search(), LLMReasoner(Client())).ask('Кто присваивает номер ФЛС?')
    assert answer.status == 'answer' and len(answer.summary) == 1
    assert 'ФЭУ' in answer.summary[0].text and 'разрядов' not in answer.summary[0].text


@pytest.mark.parametrize('include_old,status', [(True, 'clarify'), (False, 'answer')])
def test_uncertain_conflict_matters_only_when_both_sides_are_actually_used(include_old, status):
    from regnav.core.revisions import RevisionRegistry
    chunks = [Chunk('old', 'old', 'Старый порядок', '2.3', '', 'Номер присваивает сотрудник ПФО.'),
              Chunk('new', 'new', 'Новый порядок', '2.2', '', 'Номер присваивает сотрудник ФЭУ.'),
              Chunk('other', 'other', 'Дополнение', '2.2', '', 'Номер присваивает сотрудник ФЭУ по данным карточки проекта.')]
    class Search:
        def __init__(self):
            self.chunks = chunks

        def retrieve(self, *args):
            return [('номер', [Hit(c, 1, 1, {}) for c in self.chunks])]

    class Reasoner:
        def rewrite(self, question, history):
            return question

        def checklist(self, question, hits):
            selected = chunks[:2] if include_old else chunks[1:]
            return {'status': 'answer', 'kind': 'fact',
                    'summary': [{'text': c.text, 'evidence': [{'chunk_id': c.chunk_id, 'quote': c.text}]} for c in selected],
                    'steps': [], 'missing_information': [], 'clarifying_question': None,
                    '_audit': {'summary_supported': [True, True], 'steps_supported': [], 'complete': True,
                               'ordered': True, 'status_supported': True, 'missing_information': [], 'conflicts': []}}
    registry = RevisionRegistry({'documents': {'old': {'effective_from': '2017-05-01', 'uncertainty': 'Применимость не подтверждена'},
                                               'new': {'effective_from': '2021-12-01'}, 'other': {'effective_from': '2024-12-28'}},
        'conflicts': [{'type': 'possible_conflict', 'doc_ids': ['old', 'new', 'other'],
                       'message': 'Возможное расхождение источников.', 'evidence': []}]})
    answer = Navigator(Search(), Reasoner(), registry=registry).ask('Кто присваивает номер?')
    assert answer.status == status and len(answer.summary) == 2
def test_replay_queue_follows_questions_rather_than_prioritized_collection_order():
    from scripts.verify_e3 import ordered_replay, ReplayClient
    rows = [{'id': key, 'calls': [{'system': key, 'user': key, 'response': key}]} for key in ['b', 'a']]
    client = ReplayClient(ordered_replay({'results': rows}, [{'id': 'a'}, {'id': 'b'}]))
    assert client.complete('a', 'a') == 'a'
    assert client.complete('b', 'b') == 'b'


def test_composite_fact_selection_payload_contains_only_its_current_question():
    from regnav.core.pipeline import LLMReasoner
    class Client:
        def __init__(self):
            self.questions = []

        def complete(self, system, user, **kwargs):
            if 'Проверь уместность' in user:
                return json.dumps({'relevant': True})
            if 'независимый проверяющий' in user:
                return json.dumps({'summary_supported': {'0': True, '1': True}, 'steps_supported': {},
                                   'complete': True, 'ordered': True, 'status_supported': True,
                                   'missing_information': [], 'conflicts': []})
            data = json.loads(user.split('Данные:\n', 1)[1].split('\n\nЗадание:\n', 1)[0])
            self.questions.append(data['question'])
            return json.dumps({'unit_ids': ['c1s0' if data['question'].startswith('Кому') else 'c2s0']})
    client = Client()
    hits = [Hit(Chunk('one', 'd', 'Регламент', '1', '', 'Карточка направляется в центр трансфера технологий.'), 1, 1, {}),
            Hit(Chunk('two', 'd', 'Регламент', '2', '', 'Номер присваивает сотрудник финансового управления.'), 1, 1, {})]
    answer = LLMReasoner(client).checklist('Кому направить карточку проекта? Кто присваивает номер проекта?', hits)
    assert client.questions == ['Кому направить карточку проекта', 'Кто присваивает номер проекта']
    assert len(answer['summary']) == 2


@pytest.mark.parametrize('retry_id,expected', [('c2s0', 'answer'), ('c3s0', 'not_found'), ('c1s0', 'error')])
def test_single_irrelevant_selection_is_retried_once_and_cannot_reuse_rejected_id(retry_id, expected):
    from regnav.core.pipeline import LLMReasoner
    class Client:
        selections = 0

        def complete(self, system, user, **kwargs):
            if 'Проверь уместность' in user:
                candidate = json.loads(user.split('\nКандидат:\n', 1)[1])['candidate']
                return json.dumps({'relevant': candidate['id'] == 'c2s0'})
            if 'независимый проверяющий' in user:
                return json.dumps({'summary_supported': {'0': True} if expected == 'answer' else {},
                                   'steps_supported': {}, 'complete': expected == 'answer', 'ordered': True,
                                   'status_supported': True, 'missing_information': [], 'conflicts': []})
            self.selections += 1
            if self.selections > 1:
                assert 'c1s0' not in kwargs['response_schema']['properties']['unit_ids']['items']['enum']
            return json.dumps({'unit_ids': ['c1s0' if self.selections == 1 else retry_id]})
    chunks = [Chunk('a', 'd', 'Регламент', '1', '', 'Отправитель отвечает за достоверность сведений.'),
              Chunk('b', 'd', 'Регламент', '2', '', 'Карточка направляется в центр трансфера технологий.'),
              Chunk('c', 'd', 'Регламент', '3', '', 'Форма карточки содержит номер проекта.')]
    class Search:
        def __init__(self):
            self.chunks = chunks

        def retrieve(self, *args):
            return [('карточка', [Hit(c, 1, 1, {}) for c in chunks])]
    client = Client()
    answer = Navigator(Search(), LLMReasoner(client)).ask('Кому направить карточку проекта?')
    assert client.selections == 2 and answer.status == expected
    if expected == 'answer':
        assert 'центр трансфера' in answer.summary[0].text
    else:
        assert not answer.summary


def test_unrelated_date_warnings_do_not_qualify_used_sources_but_related_editions_remain():
    from regnav.core.pipeline import Answer
    from regnav.core.grounding import Claim, Evidence
    same = 'Дата начала действия не установлена.'
    answer = Answer('answer', 'вопрос', summary=[Claim('текст', [Evidence('c', 'текст', 'used', 'Название', '1')])],
        warnings=['Чужой документ не подписан.', same, same, 'Редакции различаются.',
                  'Источник «Чужая таблица»: 5 формул без результатов.'],
        applicability=[{'doc_ids': ['unrelated'], 'message': 'Чужой документ не подписан.'},
                       {'doc_ids': ['used'], 'message': same}, {'doc_ids': ['unrelated'], 'message': same},
                       {'doc_ids': ['used', 'old'], 'message': 'Редакции различаются.'}],
        sources=[{'doc_id': 'used', 'title': 'Название'}, {'doc_id': 'old', 'title': 'Старая редакция'},
                 {'doc_id': 'unrelated', 'title': 'Чужая таблица'}])
    result = Navigator._scope_used_evidence(answer)
    assert result.warnings == [same, 'Редакции различаются.']
    assert {s['doc_id'] for s in result.sources} == {'used', 'old'}
    assert len(result.applicability) == 2


@pytest.mark.parametrize('complete,supported,status', [(True, True, 'answer'), (False, True, 'partial'), (True, False, 'error')])
def test_pruned_factual_answer_requires_a_new_completeness_and_support_check(complete, supported, status):
    from regnav.core.pipeline import LLMReasoner
    class Client:
        audits = 0

        def complete(self, system, user, **kwargs):
            if 'Проверь уместность' in user:
                return json.dumps({'relevant': True})
            if 'независимый проверяющий' in user:
                self.audits += 1
                if self.audits == 2:
                    view = json.loads(user.split('\nЧерновик:\n', 1)[1].split('\nПроверяй только', 1)[0])
                    assert view['summary'] == [{'unit_id': 'c1s0'}]
                    assert 'Форму заявки' in user  # Full evidence remains available.
                return json.dumps({'summary_supported': {'0': True, '1': False} if self.audits == 1 else {'0': supported},
                                   'steps_supported': {}, 'complete': True if self.audits == 1 else complete,
                                   'ordered': True, 'status_supported': True, 'missing_information': [], 'conflicts': []})
            return json.dumps({'unit_ids': ['c1s0', 'c2s0']})
    chunks = [Chunk('a', 'd', 'Регламент', '1', '', 'Решение о командировке принимает руководитель подразделения.'),
              Chunk('b', 'd', 'Регламент', '2', '', 'Форму заявки хранит кадровое подразделение.')]
    class Search:
        def __init__(self):
            self.chunks = chunks

        def retrieve(self, *args):
            return [('решение', [Hit(c, 1, 1, {}) for c in chunks])]
    client = Client()
    answer = Navigator(Search(), LLMReasoner(client)).ask('Кто принимает решение о командировке?')
    assert client.audits == 2 and answer.status == status
    if status != 'error':
        assert len(answer.summary) == 1 and answer.verification['rechecked_after_pruning'] is True
        assert answer.verification['pruned_summary_count'] == 1
    else:
        assert not answer.summary
