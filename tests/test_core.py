import json

import pytest

from regnav.core.parse import split_document
from regnav.core.pipeline import ExtractiveReasoner, LLMReasoner, Navigator
from regnav.core.search import HybridSearcher
from regnav.core.verify import quote_in_text

TRAVEL = """Приложение к приказу
от 25.05.2017 №591-1
РЕГЛАМЕНТ
о командировании работников
1. Общие положения
1.1. Регламент определяет порядок направления
работников в служебные командировки и возмещения расходов.
1.2. Срок командировки определяется руководителем с учетом объема работы.
2. Порядок оформления командировки
2.1. Работник не позднее чем за 10 рабочих дней до начала командировки
представляет служебную записку на имя проректора.
2.2. Приказ о командировании оформляет отдел кадров на основании служебной записки.
3. Отчет о командировке
3.1. В течение 3 рабочих дней после возвращения работник представляет авансовый от-
чет с приложением документов, подтверждающих расходы.
"""

VACATION = """ПОЛОЖЕНИЕ об отпусках работников
1. Ежегодный оплачиваемый отпуск предоставляется работникам согласно графику отпусков.
2. О времени начала отпуска работник должен быть извещен под роспись не позднее чем за две недели.
"""


@pytest.fixture
def chunks():
    return split_document([TRAVEL], "travel", "Регламент о командировании") + split_document(
        [VACATION], "vac", "Положение об отпусках"
    )


def test_split_by_clauses(chunks):
    clauses = [c.clause for c in chunks if c.doc_id == "travel"]
    assert "прил., п. 2.1" in clauses and "прил., п. 3.1" in clauses
    c21 = next(c for c in chunks if c.clause.endswith("2.1"))
    assert "служебную записку" in c21.text
    assert "Порядок оформления командировки" in c21.heading
    # дата «25.05.2017» не стала пунктом
    assert not any(c.clause.startswith("25") for c in chunks)
    # перенос слова «от-\nчет» склеен
    assert "авансовый отчет" in next(c for c in chunks if c.clause.endswith("3.1")).text


def test_quote_verification():
    text = "Работник не позднее чем за 10 рабочих дней до начала командировки представляет служебную записку."
    assert quote_in_text("не позднее чем за 10 рабочих дней до начала командировки", text)
    assert quote_in_text("НЕ ПОЗДНЕЕ чем за 10  рабочих\nдней ... служебную записку", text)
    assert not quote_in_text("не позднее чем за 5 рабочих дней до начала командировки", text)
    assert not quote_in_text("за 10 дней", text)  # слишком короткая


def test_search_finds_travel(chunks):
    s = HybridSearcher(chunks)
    hits = s.search("как оформить командировку", k=3)
    assert hits[0].chunk.doc_id == "travel"


def test_extractive_answer_and_refusal(chunks):
    nav = Navigator(HybridSearcher(chunks), ExtractiveReasoner())
    a = nav.ask("Как оформить командировку?")
    assert a.status == "answer" and a.steps
    assert all(quote_in_text(s.quote, next(c.text for c in chunks if c.chunk_id == s.chunk_id)) for s in a.steps)
    assert nav.ask("Как получить ипотеку на квартиру?").status == "not_found"


class FakeClient:
    """Скриптованная LLM: релевантность — по ключевому слову, чек-лист — заранее заданный."""

    def __init__(self, checklist: dict, keyword: str = "командир"):
        self.checklist, self.keyword = checklist, keyword

    def complete(self, system, user, *, temperature=0.0):
        if '"relevant"' in user:
            frag = user.split("Фрагмент", 1)[1]
            return json.dumps({"relevant": self.keyword in frag.lower()})
        return json.dumps(self.checklist, ensure_ascii=False)


def _cid(chunks, suffix):
    return next(c.chunk_id for c in chunks if c.clause.endswith(suffix))


def test_hallucinated_quote_is_dropped(chunks):
    fake = FakeClient({"status": "answer", "steps": [
        {"action": "Подайте служебную записку", "chunk_id": _cid(chunks, "2.1"),
         "quote": "не позднее чем за 10 рабочих дней до начала командировки"},
        {"action": "Получите аванс наличными", "chunk_id": _cid(chunks, "2.1"),
         "quote": "аванс выдается наличными в кассе в день отъезда"},  # такого нет
        # верная цитата, но chunk_id перепутан — должен переназначиться
        {"action": "Сдайте авансовый отчет", "chunk_id": _cid(chunks, "2.1"),
         "quote": "В течение 3 рабочих дней после возвращения работник представляет авансовый отчет"},
    ]})
    a = Navigator(HybridSearcher(chunks), LLMReasoner(fake), max_context=10).ask("Как оформить командировку?")
    assert a.status == "answer"
    assert [s.action for s in a.steps] == ["Подайте служебную записку", "Сдайте авансовый отчет"]
    assert a.steps[1].chunk_id == _cid(chunks, "3.1")
    assert a.dropped_steps == 1


def test_all_quotes_fake_means_refusal(chunks):
    fake = FakeClient({"status": "answer", "steps": [
        {"action": "x", "chunk_id": _cid(chunks, "2.1"), "quote": "командировка оформляется через госуслуги онлайн"}]})
    a = Navigator(HybridSearcher(chunks), LLMReasoner(fake)).ask("Как оформить командировку?")
    assert a.status == "not_found"


def test_clarify(chunks):
    fake = FakeClient({"status": "clarify", "clarifying_question": "Вы штатный сотрудник или совместитель?"})
    a = Navigator(HybridSearcher(chunks), LLMReasoner(fake)).ask("Как оформить командировку?")
    assert a.status == "clarify" and "совместитель" in a.clarifying_question


def test_broken_llm_json_falls_back(chunks):
    class Broken(FakeClient):
        def complete(self, system, user, *, temperature=0.0):
            if '"relevant"' in user:
                return super().complete(system, user)
            return "Вот ваш ответ: {сломанный json"
    a = Navigator(HybridSearcher(chunks), LLMReasoner(Broken({}))).ask("Как оформить командировку?")
    assert a.status == "answer" and a.steps  # extractive-фолбэк
