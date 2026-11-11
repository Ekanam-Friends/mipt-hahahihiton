"""Download the official Drive snapshot; retain provenance and validate containers.

Run from repository root: .venv/Scripts/python scripts/download_official.py
No credentials, document parsing or model API calls are involved.
"""
import hashlib
import html
import json
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/official"
FOLDER = "https://drive.google.com/drive/folders/1aiZJAAns_mM5amYpxwfflWu64ZE7KIcy"


def now():
    return datetime.now(timezone.utc).isoformat()


def validate(path, fmt):
    if fmt == "pdf":
        import pymupdf
        with pymupdf.open(path) as doc:
            if not len(doc):
                raise ValueError("PDF has no pages")
    else:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
            marker = "word/document.xml" if fmt == "docx" else "xl/workbook.xml"
            if bad or marker not in z.namelist():
                raise ValueError(f"Invalid {fmt} container: {bad}")


def fetch(item):
    fid, name = item
    fmt = name.rsplit(".", 1)[1].lower()
    path = DATA / "raw" / (fid + "." + fmt)
    record = dict(id=fid, title=name.rsplit(".", 1)[0], original_name=name,
                  url=f"https://drive.google.com/file/d/{fid}/view",
                  local_path=path.relative_to(ROOT).as_posix(), format=fmt,
                  doc_type="official", source=FOLDER,
                  access_status="public_link_download",
                  external_api_allowed=True,
                  access_basis="User confirmed all official case materials permissible, 2026-11-11",
                  processing_status="downloaded_not_indexed")
    try:
        if not path.exists():
            for attempt in range(3):
                try:
                    with httpx.Client(follow_redirects=True, timeout=180) as client:
                        response = client.get("https://drive.google.com/uc", params={"export": "download", "id": fid})
                        response.raise_for_status()
                        payload = response.content
                    tmp = path.with_suffix(path.suffix + ".part")
                    tmp.write_bytes(payload)
                    validate(tmp, fmt)
                    tmp.replace(path)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)
            downloaded = now()
        else:
            validate(path, fmt)
            downloaded = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        record.update(downloaded_at=downloaded, verified_at=now(),
                      uploaded_at=None, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      size_bytes=path.stat().st_size, download_status="ok")
    except Exception as exc:
        record.update(download_status="error", processing_status="blocked", error=str(exc))
    print(f"{record['download_status']}: {name}", flush=True)
    return record


def main():
    (DATA / "raw").mkdir(parents=True, exist_ok=True)
    (DATA / "evidence").mkdir(exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        response = client.get(FOLDER)
        response.raise_for_status()
    (DATA / "evidence/folder.html").write_text(response.text, encoding="utf-8")
    matches = re.findall(r'data-id="([^\"]+)"[^>]*[\s\S]{0,600}?data-tooltip="([^\"]+\.(?:pdf|docx|xlsx))', response.text)
    items = list(dict.fromkeys((fid, html.unescape(name)) for fid, name in matches))
    if len(items) != 20:
        raise ValueError(f"Expected 20 files, found {len(items)}; inspect folder snapshot")
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(fetch, items))
    (DATA / "manifest.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    report = dict(checked_at=now(), source=FOLDER, expected=20, found=len(items),
                  downloaded=sum(r["download_status"] == "ok" for r in records),
                  formats={f: sum(r["format"] == f for r in records) for f in ("pdf", "docx", "xlsx")},
                  bytes=sum(r.get("size_bytes", 0) for r in records))
    (DATA / "download-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["downloaded"] == 20 else 1


if __name__ == "__main__":
    raise SystemExit(main())
