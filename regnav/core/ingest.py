"""Manifest → fingerprinted extraction cache → located chunks and per-file report."""
from __future__ import annotations

import hashlib
import copy
import html
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .extract import VERSION, extract
from .parse import Chunk, split_document, _split_long

PAGE_SEP = "\n\f\n"


def corrected_extraction(result: dict, doc_id: str, data_dir: Path) -> dict:
    """Apply reviewed, source-hash-bound OCR repairs without altering the raw cache."""
    path = data_dir / "ocr-corrections.json"
    if not path.exists():
        return result
    repairs = json.loads(path.read_text(encoding="utf-8")).get(doc_id, [])
    if not repairs:
        return result
    result = copy.deepcopy(result)
    result["corrections"] = []
    for repair in repairs:
        if repair["source_sha256"] != result["sha256"]:
            raise ValueError("OCR correction belongs to another source snapshot: " + doc_id)
        matches = [b for b in result["blocks"] if b.get("page") == repair["page"]]
        if len(matches) != 1:
            raise ValueError("OCR correction no longer matches extraction: " + doc_id)
        before_count = matches[0]["text"].count(repair["before"])
        if before_count == 0 and matches[0]["text"].count(repair["after"]) == repair.get("already_correct_count", 1):
            result["corrections"].append({**repair, "state": "already_correct"})
            continue
        if before_count != 1:
            raise ValueError("OCR correction no longer matches extraction: " + doc_id)
        matches[0]["text"] = matches[0]["text"].replace(repair["before"], repair["after"], 1)
        result["corrections"].append(repair)
    return result


def _write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def load_manifest(data_dir: Path) -> list[dict]:
    records = [json.loads(line) for line in (data_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [r["id"] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Повторяющиеся ID в манифесте")
    for record in records:
        if Path(record["id"]).name != record["id"] or any(c in record["id"] for c in '/\\:') or record["id"] in {".", ".."}:
            raise ValueError("Небезопасный ID в манифесте")
    relations_path = data_dir / "relations.json"
    if relations_path.exists():
        relations = json.loads(relations_path.read_text(encoding="utf-8"))
        for record in records:
            record["relations"] = record.get("relations", []) + relations.get(record["id"], [])
    return records


def source_path(record: dict, data_dir: Path) -> Path:
    path = Path(record["local_path"])
    if path.is_absolute():
        return path
    for root in (data_dir.resolve(), *data_dir.resolve().parents):
        candidate = root / path
        if candidate.is_file():
            return candidate
    return data_dir / path


def extract_with_ocr(path: str, dpi: int = 300) -> tuple[list[str], int]:
    result = extract(Path(path), dpi=dpi)
    return [b["text"] for b in result["blocks"]], len(result["ocr_pages"])


def _job(args):
    record, data_name, force = args
    data_dir = Path(data_name)
    doc_id = record["id"]
    cache = data_dir / "extracted" / f"{doc_id}.json"
    entry = {"id": doc_id, "title": record["title"], "status": "error", "warnings": [], "chunks": 0}
    try:
        path = source_path(record, data_dir)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entry.update(sha256=digest, format=path.suffix.lower().lstrip("."))
        if record.get("sha256") and digest != record["sha256"]:
            entry["warnings"].append("SHA-256 отличается от снимка манифеста")
        result = None
        if cache.exists() and not force:
            try:
                old = json.loads(cache.read_text(encoding="utf-8"))
                if old.get("sha256") == digest and old.get("version") == VERSION:
                    result = old
            except (ValueError, OSError):
                pass
        entry["cached"] = result is not None
        if result is None:
            result = extract(path)
            result["sha256"] = digest
            _write(cache, result)
        result = corrected_extraction(result, doc_id, data_dir)
        entry["ocr_corrections"] = result.get("corrections", [])
        (data_dir / "text" / f"{doc_id}.txt").write_text(PAGE_SEP.join(b["text"] for b in result["blocks"]), encoding="utf-8")
        entry["warnings"].extend(result["warnings"])
        entry.update({k: result[k] for k in ("pages", "ocr_pages", "empty_pages", "formula_count", "missing_formula_values")})
        entry["blocks"] = len(result["blocks"])
        entry["empty_blocks"] = sum(not b["text"].strip() for b in result["blocks"])
        entry["status"] = "warning" if entry["warnings"] else "ok"
    except Exception as error:
        entry["error"] = f"{type(error).__name__}: {error}"
        cache.unlink(missing_ok=True)
        (data_dir / "text" / f"{doc_id}.txt").unlink(missing_ok=True)
        (data_dir / "view" / f"{doc_id}.html").unlink(missing_ok=True)
    return entry


def build_texts(data_dir: Path, workers: int = 6, force: bool = False) -> dict:
    data_dir = Path(data_dir)
    for folder in ("text", "extracted"):
        (data_dir / folder).mkdir(parents=True, exist_ok=True)
    jobs = [(r, str(data_dir.resolve()), force) for r in load_manifest(data_dir)]
    if workers <= 1:
        entries = list(map(_job, jobs))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            entries = list(pool.map(_job, jobs))
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "extractor_version": VERSION, "files": entries}
    _write(data_dir / "import-report.json", report)
    return report


def build_chunks(data_dir: Path) -> list[Chunk]:
    data_dir = Path(data_dir)
    chunks = []
    report = json.loads((data_dir / "import-report.json").read_text(encoding="utf-8"))
    entries = {e["id"]: e for e in report["files"]}
    (data_dir / "view").mkdir(exist_ok=True)
    for record in load_manifest(data_dir):
        entry = entries[record["id"]]
        if entry["status"] == "error":
            continue
        cache = json.loads((data_dir / "extracted" / f"{record['id']}.json").read_text(encoding="utf-8"))
        cache = corrected_extraction(cache, record['id'], data_dir)
        meta = {**record, "source_sha256": cache["sha256"]}
        blocks = cache["blocks"]
        if entry["format"] in {"pdf", "docx"}:
            doc_chunks = split_document([b["text"] for b in blocks], record["id"], record["title"], meta,
                                        preserve_numeric=entry["format"] == "docx")
            if entry["format"] == "docx":
                for c in doc_chunks:
                    selected = blocks[(c.page or 1) - 1]
                    c.page = None
                    last = blocks[c.meta["source_end"] - 1]
                    c.meta = {**c.meta, "locator": selected["locator"],
                              "locator_end": last["locator"], "style": selected.get("style", ""),
                              "source_locations": [b["locator"] for b in blocks[c.meta["source_start"] - 1:c.meta["source_end"]]]}
        else:
            doc_chunks = []
            for block in blocks:
                for part in _split_long(block["text"]):
                    doc_chunks.append(Chunk("", record["id"], record["title"], block["locator"],
                                            f"Лист {block['sheet']}", part, None,
                                            {**meta, **{k: v for k, v in block.items() if k != "text"}}))
        duplicates = {}
        for c in doc_chunks:
            c.meta = dict(c.meta)
            if c.page:
                c.meta["locator"] = f"page={c.page}"
            loc = c.meta["locator"]
            signature = hashlib.sha256((loc + "\0" + c.clause + "\0" + c.text).encode()).hexdigest()[:20]
            count = duplicates.get(signature, 0)
            duplicates[signature] = count + 1
            c.chunk_id = f"{record['id']}#{signature}" + (f"-{count}" if count else "")
            c.meta["local_source"] = str(source_path(record, data_dir).resolve())
            c.meta["source_fragment"] = loc
            c.meta["view_path"] = str(data_dir / "view" / f"{record['id']}.html") + "#" + c.chunk_id.split("#", 1)[1]
            c.meta["source_url"] = record.get("url")
            if c.page and record.get("url"):
                c.meta["url"] = record["url"].split("#")[0] + f"#page={c.page}"
            chunks.append(c)
        # Self-contained UTF-8 viewer: escaped original extraction and stable fragment anchors.
        esc = lambda value: html.escape(str(value), quote=True)
        sections = []
        for c in doc_chunks:
            anchor = c.chunk_id.split("#", 1)[1]
            sections.append(f'<section id="{esc(anchor)}"><h2>{esc(c.ref())}</h2>'
                            f'<p>{esc(c.meta["source_fragment"])} — {esc(c.meta.get("locator_end", ""))}</p>'
                            f'<pre>{esc(c.text)}</pre></section>')
        original = "".join(f'<h3>{esc(b["locator"])}</h3><pre>{esc(b["text"])}</pre>' for b in blocks)
        viewer = ('<!doctype html><html lang="ru"><meta charset="utf-8">'
                  '<meta name="viewport" content="width=device-width"><title>' + esc(record["title"]) + '</title>'
                  '<style>body{max-width:1000px;margin:2rem auto;padding:1rem;font:16px sans-serif}'
                  'pre{white-space:pre-wrap;overflow-wrap:anywhere}section{border-top:1px solid #ccc;padding:1rem}'
                  'section:target{background:#fff3bb}</style><h1>' + esc(record["title"]) + '</h1>'
                  '<p>Локальное извлечение, не визуальная копия оригинала. SHA-256: ' + esc(cache["sha256"]) + '</p>'
                  '<a href="' + esc(record.get("url", "")) + '">Оригинал</a>' + "".join(sections)
                  + '<details><summary>Полный извлечённый текст с адресами</summary>' + original + '</details></html>')
        (data_dir / "view" / f"{record['id']}.html").write_text(viewer, encoding="utf-8")
        entry["chunks"] = len(doc_chunks)
        if not doc_chunks:
            entry.update(status="error", error="Извлечение не дало непустых фрагментов")
    with (data_dir / "chunks.jsonl").open("w", encoding="utf-8") as output:
        for chunk in chunks:
            output.write(json.dumps(chunk.to_dict(), ensure_ascii=False, default=str) + "\n")
    report["summary"] = {"files": len(entries), "ok": sum(e["status"] == "ok" for e in entries.values()),
                         "warning": sum(e["status"] == "warning" for e in entries.values()),
                         "error": sum(e["status"] == "error" for e in entries.values()), "chunks": len(chunks)}
    _write(data_dir / "import-report.json", report)
    return chunks


def load_chunks(data_dir: Path) -> list[Chunk]:
    with open(data_dir / "chunks.jsonl", encoding="utf-8") as f:
        return [Chunk(**json.loads(line)) for line in f if line.strip()]
