"""Offline retrieval acceptance; no LLM quality claims. Exit 1 on any missing gold clause."""
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from regnav.core.ingest import load_chunks
from regnav.core.pipeline import ExtractiveReasoner, Navigator
from regnav.core.revisions import RevisionRegistry
from regnav.core.search import HybridSearcher


def main():
    root = Path(__file__).resolve().parents[1]
    data = root / "data/official"
    chunks = load_chunks(data)
    by_id = {c.chunk_id: c for c in chunks}
    registry = RevisionRegistry.load(data / "revisions.json")
    qs_path = root / "eval/e2-questions.jsonl"
    questions = [json.loads(l) for l in qs_path.read_text(encoding="utf-8").splitlines()]
    manifest = [json.loads(l) for l in (data / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    for m in manifest:
        assert hashlib.sha256((root / m["local_path"]).read_bytes()).hexdigest() == m["sha256"], m["id"]
        assert registry.documents[m["id"]]["sha256"] == m["sha256"]
    for entry in registry.documents.values():
        for e in entry["evidence"]:
            assert e["quote"] in by_id[e["chunk_id"]].text
    for q in questions:
        for e in q["expected"]:
            for cid in e["chunk_ids"]:
                c = by_id[cid]
                assert c.doc_id == e["doc_id"] and e["quote"].lower() in c.text.lower()
                viewer, anchor = c.meta["view_path"].split("#", 1)
                assert f'id="{anchor}"' in (root / viewer).read_text(encoding="utf-8")
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "corpus_downloaded_at": sorted({m["downloaded_at"] for m in manifest}),
        "corpus_files": len(manifest), "chunks": len(chunks), "gold_sha256": hashlib.sha256(qs_path.read_bytes()).hexdigest(),
        "scope": "retrieval and applicability only; required answer elements are annotations for E3, not measured generation",
        "embeddings": "not enabled; local lexical baseline compared to local expanded/content hybrid", "runs": {}}
    for mode in ["baseline", "enhanced"]:
        searcher = HybridSearcher(chunks, expanded=mode == "enhanced")
        nav = Navigator(searcher, ExtractiveReasoner(), registry=registry)
        rows = []
        for q in questions:
            started = time.perf_counter()
            if mode == "baseline":
                hits = searcher.search(q["question"], k=10)
                trace = [{"query": q["question"], "chunk_ids": [h.chunk.chunk_id for h in hits]}]
            else:
                hits, trace = nav.retrieve(q["question"])
            ids, dids = {h.chunk.chunk_id for h in hits}, {h.chunk.doc_id for h in hits}
            checks = [{"doc_id": e["doc_id"], "chunk_ids": e["chunk_ids"], "document_found": e["doc_id"] in dids,
                       "fragment_found": bool(ids.intersection(e["chunk_ids"]))} for e in q["expected"]]
            issues = registry.assess(dids, q["as_of"])
            expected_unknown = q["applicability"] == "uncertain"
            temporal_ok = not expected_unknown or any(i["type"] == "uncertain" and set(i["doc_ids"]).intersection(e["doc_id"] for e in q["expected"]) for i in issues)
            if q["applicability"] == "possible_conflict":
                temporal_ok = any(i["type"] == "possible_conflict" and len(i["sources"]) >= 2 for i in issues)
            ok = all(c["fragment_found"] for c in checks) and temporal_ok
            row = {"id": q["id"], "question": q["question"], "passed": ok, "checks": checks,
                   "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                   "applicability_passed": temporal_ok, "trace": trace, "issues": issues,
                   "hits": [{"chunk_id": h.chunk.chunk_id, "doc_id": h.chunk.doc_id, "clause": h.chunk.clause,
                             "score": h.score, "coverage": h.coverage, "url": h.chunk.meta.get("url"),
                             "view_path": h.chunk.meta.get("view_path")} for h in hits]}
            rows.append(row)
            if not ok:
                print(mode, "FAIL", q["id"], [c["chunk_ids"] for c in checks if not c["fragment_found"]], "temporal", temporal_ok)
        report["runs"][mode] = {"questions": len(rows), "passed": sum(r["passed"] for r in rows),
            "all_documents": sum(all(c["document_found"] for c in r["checks"]) for r in rows),
            "all_fragments": sum(all(c["fragment_found"] for c in r["checks"]) for r in rows), "results": rows}
    # Verify the public answer path exposes ambiguity and dates, rather than only the registry API.
    conflict_q = next(q for q in questions if q["id"] == "fls-conflict")
    conflict = nav.ask(conflict_q["question"], as_of=conflict_q["as_of"])
    future_q = next(q for q in questions if q["id"] == "borrowing")
    future = nav.ask(future_q["question"], as_of="2026-11-02")
    travel = nav.ask(questions[0]["question"], as_of="2026-11-12")
    runtime = {
        "conflict_with_all_source_links": any(i["type"] == "possible_conflict" for i in conflict.applicability)
            and {e["doc_id"] for e in conflict_q["expected"]}.issubset(s["doc_id"] for s in conflict.sources),
        "before_effective_date_clarifies": future.status == "clarify" and any(i["type"] == "not_yet_effective" for i in future.applicability),
        "unknown_approval_is_explicit": any(i["type"] == "uncertain" for i in travel.applicability) and bool(travel.warnings),
    }
    report["runtime_checks"] = runtime
    out = data / "e2-search-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({mode: {k: v for k, v in run.items() if k != "results"} for mode, run in report["runs"].items()}, ensure_ascii=False))
    print("Runtime:", runtime)
    return int(report["runs"]["enhanced"]["passed"] != len(questions) or not all(runtime.values()))


if __name__ == "__main__":
    raise SystemExit(main())
