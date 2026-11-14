from dataclasses import replace

import pytest

from regnav.core.parse import Chunk
from regnav.core.pipeline import ExtractiveReasoner, Navigator
from regnav.core.revisions import RevisionRegistry
from regnav.core.search import Hit, HybridSearcher, expand_query, split_query


def chunk(cid, did, text):
    return Chunk(cid, did, did, "1", "", text, meta={"url": f"https://example.org/{did}"})


def test_split_independent_parts_and_keep_antecedent():
    parts = split_query("Как открыть ФЛС и кто присваивает его номер?")
    assert len(parts) == 2 and "ФЛС" in parts[1]
    parts = split_query("Кто утверждает график концертного зала? Как получить доступ к сервисам ЦОД?")
    assert len(parts) == 2 and "концертного" not in parts[1]
    assert len(split_query("Кому передать карточку проекта и скан договора?")) == 1


def test_aliases_and_number_variants():
    assert "электронный бюджет" in expand_query("ЭБ")
    assert "3065-1" in expand_query("3065 – 1")
    assert "командировка" in expand_query("Рабочая поездка")


def test_empty_search_and_invalid_k():
    assert HybridSearcher([]).search("ФЛС") == []
    assert HybridSearcher([chunk("a", "a", "номер счета")]).search("номер", -2) == []


@pytest.mark.parametrize("day,expected", [("2026-01-01", "not_yet_effective"), ("2026-02-01", None),
                                         ("2026-03-01", "expired")])
def test_effective_boundaries_ignore_upload_date(day, expected):
    r = RevisionRegistry({"documents": {"a": {"issued_on": "2026-01-01", "effective_from": "2026-02-01",
        "effective_to": "2026-03-01", "uploaded_at": "2030-01-01"}}})
    issues = r.assess(["a"], day)
    assert ([i["type"] for i in issues] or [None]) == [expected]


def test_unknown_date_and_invalid_date():
    r = RevisionRegistry({"documents": {"a": {"uploaded_at": "2026-01-01"}}})
    assert r.assess(["a"], "2026-11-12")[0]["type"] == "uncertain"
    with pytest.raises(ValueError):
        r.assess(["a"], "2026-99-01")


def test_compound_keeps_each_budget_and_temporal_evidence():
    a, b, e = chunk("a", "a", "оформление командировки"), chunk("b", "b", "доступ к сервисам ЦОД"), chunk("e", "a", "дата действия")

    class Search:
        chunks = [a, b, e]

        def retrieve(self, query, k, per_part):
            return [("командировка", [Hit(a, 1, 1, {})]), ("ЦОД", [Hit(b, 1, 1, {})])]

    registry = RevisionRegistry({"documents": {"a": {"evidence": [{"chunk_id": "e"}]}}})
    nav = Navigator(Search(), ExtractiveReasoner(), k=1, max_context=1, registry=registry)
    hits, trace = nav.retrieve("two parts")
    assert {h.chunk.chunk_id for h in hits} == {"a", "b", "e"}
    assert len(trace) == 2


def test_conflict_clarifies_and_exposes_both_links():
    a, b = chunk("a", "a", "номер счета присваивает отдел А"), chunk("b", "b", "номер счета присваивает отдел Б")
    r = RevisionRegistry({"documents": {"a": {}, "b": {}}, "conflicts": [
        {"type": "conflict", "doc_ids": ["a", "b"], "message": "Ответственный не установлен."}]})
    ans = Navigator(HybridSearcher([a, b]), ExtractiveReasoner(), registry=r).ask("Кто присваивает номер счета?")
    assert ans.status == "clarify"
    assert {s["url"] for s in ans.sources} == {"https://example.org/a", "https://example.org/b"}
    assert next(i for i in ans.applicability if i["type"] == "conflict")["sources"]


def test_registry_drift_fails_loudly():
    a = chunk("a", "a", "номер счета")
    r = RevisionRegistry({"documents": {"a": {"sha256": "different"}}})
    with pytest.raises(ValueError, match="не соответствует"):
        Navigator(HybridSearcher([a]), ExtractiveReasoner(), registry=r)


def test_cell_address_boost_retrieves_exact_row():
    a = chunk("a", "a", "Финансовая структура")
    b = replace(a, chunk_id="b", text="Финансовая структура на 01.08.2025", meta={"cells": [{"address": "A2"}]})
    assert HybridSearcher([a, b]).search("Дата структуры в A2", 1)[0].chunk.chunk_id == "b"
