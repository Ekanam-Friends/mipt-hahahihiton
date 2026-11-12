"""Вопрос → проверяемый чек-лист или честный отказ.

    вопрос ─→ (переписать по истории) ─→ гибридный поиск ─→ ранний отказ по coverage
          ─→ map: каждый фрагмент проверяется на релевантность ─→ генерация чек-листа (JSON)
          ─→ проверка цитат: шаг без дословной цитаты отбрасывается ─→ ответ / отказ
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol

from .llm import LLMClient
from .search import Hit, HybridSearcher
from .text import tokenize
from .verify import quote_in_text

NOT_FOUND_MSG = (
    "В базе нет регламента или приказа, который отвечает на этот вопрос. "
    "Обратитесь в профильное подразделение (например, в Управление по работе с персоналом) "
    "или к руководителю."
)

# ------------------------------------------------------------------ модель ответа


@dataclass
class Step:
    action: str
    quote: str
    chunk_id: str
    responsible: str | None = None
    deadline: str | None = None
    documents: list[str] = field(default_factory=list)
    ref: str = ""
    url: str | None = None


@dataclass
class Answer:
    status: Literal["answer", "clarify", "not_found"]
    question: str
    steps: list[Step] = field(default_factory=list)
    clarifying_question: str | None = None
    sources: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message: str | None = None
    dropped_steps: int = 0  # сколько шагов LLM отброшено без подтверждения

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ «мышление»


class Reasoner(Protocol):
    def rewrite(self, question: str, history: list[str]) -> str: ...
    def is_relevant(self, question: str, hit: Hit) -> bool: ...
    def checklist(self, question: str, hits: list[Hit]) -> dict: ...


class ExtractiveReasoner:
    """Режим без LLM: шаги — дословные выдержки из лучших пунктов. Нужен для работы без ключей
    и как запасной путь, если LLM недоступна."""

    def __init__(self, min_coverage: float = 0.5, max_steps: int = 5):
        self.min_coverage = min_coverage
        self.max_steps = max_steps

    def rewrite(self, question: str, history: list[str]) -> str:
        return " ".join([*history[-2:], question])

    def is_relevant(self, question: str, hit: Hit) -> bool:
        return hit.coverage >= self.min_coverage

    def checklist(self, question: str, hits: list[Hit]) -> dict:
        steps = []
        for h in hits[: self.max_steps]:
            text = h.chunk.text
            # первая содержательная фраза пункта
            sent = re.split(r"(?<=[.;:])\s+", text)
            quote = next((s for s in sent if len(s) > 40), text[:300])[:400]
            steps.append({"action": quote, "quote": quote, "chunk_id": h.chunk.chunk_id})
        return {"status": "answer", "steps": steps}


SYSTEM = """Ты — помощник сотрудника МФТИ по внутренним регламентам и приказам.
Отвечай ТОЛЬКО по переданным фрагментам документов. Ничего не придумывай.
Каждый шаг обязан опираться на фрагмент: укажи его chunk_id и дословную цитату из него
(скопируй фразу символ в символ, 1–2 предложения). Шаг без цитаты не пиши.
Если во фрагментах нет ответа — status "not_found".
Если порядок действий зависит от роли (штатный сотрудник / совместитель / ППС / студент /
подразделение), а из вопроса роль не ясна — status "clarify" и короткий уточняющий вопрос.
Ответ — строго JSON без пояснений."""

CHECKLIST_FMT = """{"status": "answer" | "clarify" | "not_found",
 "clarifying_question": str | null,
 "steps": [{"action": "что сделать, повелительное наклонение",
            "responsible": "кто делает/согласует" | null,
            "deadline": "срок" | null,
            "documents": ["заявление", "служебная записка", ...],
            "chunk_id": "...", "quote": "дословная цитата"}],
 "warnings": ["противоречия между документами, устаревшие редакции"]}"""


def _parse_json(s: str) -> dict:
    s = s.strip()
    s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


class LLMReasoner:
    def __init__(self, client: LLMClient, fallback: ExtractiveReasoner | None = None):
        self.client = client
        self.fallback = fallback or ExtractiveReasoner()

    def rewrite(self, question: str, history: list[str]) -> str:
        if not history:
            return question
        user = (
            "История диалога:\n" + "\n".join(f"- {h}" for h in history[-6:]) +
            f"\n\nПоследний вопрос: {question}\n\n"
            'Перепиши последний вопрос так, чтобы он был понятен без истории. JSON: {"query": "..."}'
        )
        return _parse_json(self.client.complete(SYSTEM, user)).get("query") or question

    def is_relevant(self, question: str, hit: Hit) -> bool:
        user = (
            f"Вопрос: {question}\n\nФрагмент ({hit.chunk.ref()}):\n{hit.chunk.text}\n\n"
            'Есть ли в фрагменте информация, нужная для ответа? JSON: {"relevant": true|false}'
        )
        try:
            return bool(_parse_json(self.client.complete(SYSTEM, user)).get("relevant"))
        except Exception:
            return self.fallback.is_relevant(question, hit)

    def checklist(self, question: str, hits: list[Hit]) -> dict:
        frags = "\n\n".join(
            f"[chunk_id={h.chunk.chunk_id}] {h.chunk.ref()}\n{h.chunk.text}" for h in hits
        )
        user = f"Вопрос сотрудника: {question}\n\nФрагменты:\n{frags}\n\nФормат ответа:\n{CHECKLIST_FMT}"
        try:
            out = _parse_json(self.client.complete(SYSTEM, user))
        except Exception:
            out = {}
        return out if out.get("status") else self.fallback.checklist(question, hits)


# ------------------------------------------------------------------ конвейер


def _title_family(title: str) -> frozenset:
    return frozenset(t for t in tokenize(title) if not t.isdigit())


class Navigator:
    def __init__(self, searcher: HybridSearcher, reasoner: Reasoner, k: int = 10,
                 min_top_coverage: float = 0.34, max_context: int = 6):
        self.searcher = searcher
        self.reasoner = reasoner
        self.k = k
        self.min_top_coverage = min_top_coverage
        self.max_context = max_context

    def ask(self, question: str, history: list[str] | None = None) -> Answer:
        query = self.reasoner.rewrite(question, history or [])
        hits = self.searcher.search(query, k=self.k)

        # 1. Ранний отказ: ни один пункт не покрывает значимые слова запроса.
        if not hits or max(h.coverage for h in hits) < self.min_top_coverage:
            return Answer("not_found", question, message=NOT_FOUND_MSG)

        # 2. Map: каждый фрагмент проверяется отдельно и параллельно.
        with ThreadPoolExecutor(max_workers=8) as ex:
            flags = list(ex.map(lambda h: self.reasoner.is_relevant(query, h), hits))
        relevant = [h for h, ok in zip(hits, flags) if ok][: self.max_context]
        if not relevant:
            return Answer("not_found", question, message=NOT_FOUND_MSG)

        # 3. Генерация.
        draft = self.reasoner.checklist(query, relevant)
        status = draft.get("status", "answer")
        if status == "clarify" and draft.get("clarifying_question"):
            return Answer("clarify", question, clarifying_question=draft["clarifying_question"],
                          sources=self._sources(relevant))
        if status == "not_found":
            return Answer("not_found", question, message=NOT_FOUND_MSG)

        # 4. Проверка цитат.
        by_id = {h.chunk.chunk_id: h.chunk for h in relevant}
        steps, dropped = [], 0
        for s in draft.get("steps") or []:
            quote, cid = (s.get("quote") or "").strip(), s.get("chunk_id")
            chunk = by_id.get(cid)
            if not (chunk and quote_in_text(quote, chunk.text)):
                # LLM могла перепутать chunk_id — ищем цитату в других фрагментах
                chunk = next((c for c in by_id.values() if quote_in_text(quote, c.text)), None)
            if chunk is None:
                dropped += 1
                continue
            steps.append(Step(
                action=s.get("action") or quote, quote=quote, chunk_id=chunk.chunk_id,
                responsible=s.get("responsible"), deadline=s.get("deadline"),
                documents=list(s.get("documents") or []), ref=chunk.ref(), url=chunk.meta.get("url"),
            ))
        if not steps:
            return Answer("not_found", question, message=NOT_FOUND_MSG, dropped_steps=dropped)

        used = [by_id[s.chunk_id] for s in steps]
        warnings = list(draft.get("warnings") or [])
        warnings += self._version_warnings(used, relevant)
        if dropped:
            warnings.append(f"Отброшено шагов без подтверждающей цитаты: {dropped}.")
        return Answer("answer", question, steps=steps, sources=self._sources([h for h in relevant if h.chunk in used]),
                      warnings=warnings, dropped_steps=dropped)

    @staticmethod
    def _sources(hits: list[Hit]) -> list[dict]:
        seen, out = set(), []
        for h in hits:
            c = h.chunk
            if c.doc_id in seen:
                continue
            seen.add(c.doc_id)
            out.append({"doc_id": c.doc_id, "title": c.doc_title, "url": c.meta.get("url"),
                        "uploaded_at": c.meta.get("uploaded_at")})
        return out

    @staticmethod
    def _version_warnings(used, relevant: list[Hit]) -> list[str]:
        """Похожие по названию документы среди найденных → возможно, несколько редакций."""
        docs = {}
        for h in relevant:
            docs.setdefault(h.chunk.doc_id, h.chunk.doc_title)
        used_ids = {c.doc_id for c in used}
        out, seen = [], set()
        for a in sorted(used_ids):
            fa = _title_family(docs[a])
            for b, tb in docs.items():
                pair = frozenset((a, b))
                if b == a or pair in seen:
                    continue
                fb = _title_family(tb)
                if fa and fb and len(fa & fb) / len(fa | fb) >= 0.6:
                    seen.add(pair)
                    out.append(f"Найдено несколько редакций: «{docs[a]}» и «{tb}». Проверьте, какая действует.")
        return out
