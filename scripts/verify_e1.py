"""Reproducible acceptance evidence for the downloaded official snapshot (no API calls)."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from regnav.core.ingest import build_texts, build_chunks, load_manifest, source_path


def main():
    root = Path("data/official")
    records = load_manifest(root)
    chunks = build_chunks(root)
    before = [c.chunk_id for c in chunks]
    build_texts(root, workers=1)
    after = build_chunks(root)
    assert before == [c.chunk_id for c in after], "IDs changed on identical reimport"
    report = json.loads((root / "import-report.json").read_text(encoding="utf-8"))
    assert len(records) == 20 and report["summary"]["error"] == 0
    assert all(e["cached"] for e in report["files"])
    assert len({c.chunk_id for c in after}) == len(after)
    checked = []
    # Word soft/explicit breaks may separate runs without a w:t space.
    normalize = lambda s: re.sub(r"\s+", "", s)
    for record in records:
        source = source_path(record, root)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == record["sha256"]
        extracted = json.loads((root / "extracted" / f"{record['id']}.json").read_text(encoding="utf-8"))
        selected = [c for c in after if c.doc_id == record["id"]]
        assert selected and all(c.text.strip() for c in selected)
        for c in selected:
            viewer, anchor = c.meta["view_path"].split("#")
            assert f'id="{anchor}"' in Path(viewer).read_text(encoding="utf-8")
        detail = {"id": record["id"], "format": source.suffix, "chunks": len(selected)}
        if source.suffix == ".docx":
            # Independent XML check includes every body/table paragraph in order.
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            with ZipFile(source) as archive:
                body = ET.fromstring(archive.read("word/document.xml")).find("w:body", ns)
            paragraphs = [normalize("".join(t.text or "" for t in p.findall(".//w:t", ns)))
                          for p in body.findall(".//w:p", ns)]
            paragraphs = [p for p in paragraphs if p]
            actual = [normalize(b["text"]) for b in extracted["blocks"]]
            assert paragraphs == actual, record["title"]
            detail["body_paragraphs_including_tables"] = len(paragraphs)
        elif source.suffix == ".xlsx":
            from openpyxl import load_workbook
            workbook = load_workbook(source, data_only=False, keep_links=False)
            try:
                expected = {(s.title, c.coordinate): str(c.value) for s in workbook for row in s for c in row if c.value is not None}
                actual = {(b["sheet"], c["address"]): c["value"] for b in extracted["blocks"] for c in b["cells"]}
                assert expected == actual
                detail.update(nonempty_cells=len(expected), formulas=extracted["formula_count"],
                              missing_formula_values=len(extracted["missing_formula_values"]))
            finally:
                workbook.close()
        else:
            import pymupdf
            with pymupdf.open(source) as document:
                assert len(document) == len(extracted["blocks"])
                for number, page in enumerate(document, 1):
                    if number not in extracted["ocr_pages"]:
                        assert page.get_text("text", sort=True) == extracted["blocks"][number - 1]["text"]
            detail.update(pages=extracted["pages"], ocr_pages=extracted["ocr_pages"])
        checked.append(detail)
    result = {"verified_at": datetime.now(timezone.utc).isoformat(), "snapshot": "downloaded 2026-11-11; local SHA-256 verified",
              "files": checked, "summary": report["summary"], "stable_ids_on_cached_reimport": True,
              "all_fragment_view_anchors_exist": True, "all_nonempty_office_cells_and_paragraphs_preserved": True}
    (root / "e1-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
