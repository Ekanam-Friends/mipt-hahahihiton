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
    assert a.status == "partial" and a.summary and not a.steps
    assert all(quote_in_text(e.quote, next(c.text for c in chunks if c.chunk_id == e.chunk_id)) for claim in a.summary for e in claim.evidence)
    assert nav.ask("Как получить ипотеку на квартиру?").status == "not_found"
