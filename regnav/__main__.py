"""CLI навигатора.

  python -m regnav ingest                  # текст (+OCR) и разбор на пункты → data/chunks.jsonl
  python -m regnav search "вопрос" [-k 5]  # только поиск: какие пункты нашлись
  python -m regnav ask "вопрос"            # чек-лист или честный отказ
  python -m regnav eval                    # контрольные вопросы: acc@k и доля верных отказов
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.ingest import build_chunks, build_texts, load_chunks
from .core.llm import client_from_env
from .core.pipeline import Answer, ExtractiveReasoner, LLMReasoner, Navigator
from .core.search import HybridSearcher
from .core.revisions import RevisionRegistry


def make_navigator(data: Path) -> Navigator:
    searcher = HybridSearcher(load_chunks(data))
    client = client_from_env()
    reasoner = LLMReasoner(client) if client else ExtractiveReasoner()
    return Navigator(searcher, reasoner, registry=RevisionRegistry.load(data / "revisions.json"))


def print_answer(a) -> None:
    print("Статус:", a.status)
    print("Снимок корпуса:", ", ".join(a.corpus_snapshot) or "дата не установлена")
    if a.message:
        print(a.message)
    if a.status == "clarify":
        print("?", a.clarifying_question)
    for claim in a.summary:
        print(claim.text)
        for e in claim.evidence:
            print(f"   ↳ {e.ref}: «{e.quote}»")
            print(f"     {e.view_path or e.url}")
    for i, s in enumerate(a.steps, 1):
        extra = " · ".join(x for x in [s.responsible and f"кто: {s.responsible}",
                                        s.deadline and f"срок: {s.deadline}",
                                        s.documents and "документы: " + ", ".join(s.documents)] if x)
        print(f"{i}. {s.action}")
        if extra:
            print(f"   {extra}")
        for e in s.evidence:
            print(f"   ↳ {e.ref}: «{e.quote}»")
            print(f"     {e.view_path or e.url}")
    for conflict in a.conflicts:
        print("Расхождение:", conflict.text)
        for e in conflict.evidence:
            print(f"   ↳ {e.ref}: «{e.quote}» ({e.view_path or e.url})")
    for gap in a.missing_information:
        print("Не подтверждено:", gap)
    for w in a.warnings:
        print("⚠", w)
    print("Источники:", "; ".join(f"{s['title']} ({s['url']})" for s in a.sources))


def run_eval(data: Path, path: Path, k: int) -> int:
    nav = make_navigator(data)
    qs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    found = {1: 0, 3: 0, 5: 0, 10: 0}
    in_corpus = refusals_ok = out_corpus = false_refusals = 0
    for q in qs:
        hits = nav.searcher.search(q["question"], k=10)
        ans = nav.ask(q["question"])
        expected = set(q.get("expected_docs") or [])
        if expected:
            in_corpus += 1
            ids = [h.chunk.doc_id for h in hits]
            pos = next((i + 1 for i, d in enumerate(ids) if d in expected), None)
            for kk in found:
                found[kk] += bool(pos and pos <= kk)
            false_refusals += ans.status == "not_found"
            mark = f"@{pos}" if pos else "MISS"
        else:
            out_corpus += 1
            refusals_ok += ans.status == "not_found"
            mark = "отказ ✓" if ans.status == "not_found" else f"ОТВЕТИЛ ({ans.status})"
        print(f"{mark:>12}  {q['question']}")
    print()
    if in_corpus:
        print("поиск: " + "  ".join(f"acc@{kk}={v / in_corpus:.2f}" for kk, v in found.items()),
              f"(вопросов: {in_corpus}); ложных отказов: {false_refusals}")
    if out_corpus:
        print(f"вне корпуса: верных отказов {refusals_ok}/{out_corpus}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="regnav")
    ap.add_argument("--data", default="data", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--force", action="store_true", help="пересобрать текст, включая OCR")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--as-of", help="Дата применимости YYYY-MM-DD")
    p = sub.add_parser("ask")
    p.add_argument("question")
    p.add_argument("--json", action="store_true")
    p.add_argument("--as-of", help="Дата применимости YYYY-MM-DD")
    p = sub.add_parser("eval")
    p.add_argument("--questions", type=Path, default=Path("eval/questions.jsonl"))
    p.add_argument("-k", type=int, default=5)
    a = ap.parse_args(argv)

    if a.cmd == "ingest":
        build_texts(a.data, workers=a.workers, force=a.force)
        chunks = build_chunks(a.data)
        print(f"фрагментов: {len(chunks)} → {a.data / 'chunks.jsonl'}", file=sys.stderr)
        report = json.loads((a.data / "import-report.json").read_text(encoding="utf-8"))
        print(json.dumps(report["summary"], ensure_ascii=False), file=sys.stderr)
        if report["summary"]["error"]:
            return 1
    elif a.cmd == "search":
        s = HybridSearcher(load_chunks(a.data))
        registry = RevisionRegistry.load(a.data / "revisions.json")
        nav = Navigator(s, ExtractiveReasoner(), k=a.k, max_context=a.k, registry=registry)
        hits, trace = nav.retrieve(a.query)
        for part in trace:
            print(f"Подзадача [{part['status']}]: {part['query']}")
        for i, h in enumerate(hits, 1):
            print(f"{i}. [{h.score:.4f} cov={h.coverage:.2f} {h.ranks}] {h.chunk.ref()}")
            print("   " + h.chunk.text[:300].replace("\n", " "))
            if h.chunk.meta.get("view_path"):
                print("   Фрагмент: " + h.chunk.meta["view_path"])
        for issue in registry.assess({h.chunk.doc_id for h in hits}, a.as_of):
            print("⚠", issue["message"])
            for source in issue["sources"]:
                print(f"   {source['title']}: {source['url']}")
    elif a.cmd == "ask":
        try:
            nav = make_navigator(a.data)
        except (OSError, ValueError, KeyError):
            ans = Answer("error", a.question, message="Индекс не загружен или не соответствует реестру. Повторите импорт и проверьте каталог данных.", error_code="index_unavailable")
        else:
            ans = nav.ask(a.question, as_of=a.as_of)
        if a.json:
            print(json.dumps(ans.to_dict(), ensure_ascii=False, indent=2))
        else:
            print_answer(ans)
        return int(ans.status == "error")
    elif a.cmd == "eval":
        return run_eval(a.data, a.questions, a.k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
