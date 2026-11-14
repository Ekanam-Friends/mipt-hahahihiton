"""Evidence-backed applicability registry. Missing dates stay unknown."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


class RevisionRegistry:
    def __init__(self, data: dict | None = None):
        self.data = data or {}
        self.documents = self.data.get("documents", {})

    @classmethod
    def load(cls, path: Path):
        return cls(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else cls()

    def assess(self, doc_ids, as_of: str | None = None) -> list[dict]:
        if as_of:
            as_of = date.fromisoformat(as_of).isoformat()
        out = []
        ids = set(doc_ids)
        for did in sorted(ids):
            entry = self.documents.get(did)
            if not entry:
                continue
            issue = None
            start, end = entry.get("effective_from"), entry.get("effective_to")
            if as_of and start and as_of < start:
                issue = "not_yet_effective"
            elif as_of and end and as_of >= end:
                issue = "expired"
            elif not start or entry.get("uncertainty"):
                issue = "uncertain"
            if issue:
                message = (f"Документ начинает действовать {start}, после запрошенной даты {as_of}." if issue == "not_yet_effective" else
                           f"Документ прекратил действие {end}, до запрошенной даты {as_of}." if issue == "expired" else
                           entry.get("uncertainty") or "Дата начала действия не подтверждена.")
                out.append({"type": issue, "doc_ids": [did], "message": message,
                            "sources": [self.source(did)], "evidence": entry.get("evidence", [])})
        for conflict in self.data.get("conflicts", []):
            if len(ids.intersection(conflict["doc_ids"])) >= 2:
                out.append({**conflict, "sources": [self.source(d) for d in conflict["doc_ids"]]})
        return out

    def source(self, did):
        entry = self.documents.get(did, {})
        return {"doc_id": did, "title": entry.get("title"), "url": entry.get("url"),
                "effective_from": entry.get("effective_from"), "issued_on": entry.get("issued_on")}

    def evidence_for(self, doc_ids):
        """Include applicability clauses even when their lexical rank is low."""
        ids = set(doc_ids)
        proofs = [e["chunk_id"] for did in sorted(ids) for e in self.documents.get(did, {}).get("evidence", [])]
        for conflict in self.data.get("conflicts", []):
            if len(ids.intersection(conflict["doc_ids"])) >= 2:
                proofs.extend(e["chunk_id"] for e in conflict.get("evidence", []))
        return list(dict.fromkeys(proofs))
