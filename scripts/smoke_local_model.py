"""Check local OpenAI-compatible API with a fragment from the official corpus."""
import json
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/official"


def main():
    records = [json.loads(line) for line in (DATA / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    doc = next(r for r in records if r["format"] == "docx" and "794-1" in r["original_name"])
    with zipfile.ZipFile(ROOT / doc["local_path"]) as z:
        tree = ET.fromstring(z.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    text = "\n".join("".join(p.itertext()) for p in tree.findall(".//w:p", ns))[:2000]
    payload = dict(model="regnav-local", temperature=0, max_tokens=128,
                   messages=[dict(role="system", content="Отвечай только по фрагменту документа. Не добавляй сведения из общих знаний."),
                             dict(role="user", content=f"Фрагмент:\n{text}\n\nКратко: о чём этот документ?")])
    start = time.monotonic()
    req = urllib.request.Request("http://127.0.0.1:8087/v1/chat/completions",
                                 data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    # Disable proxy discovery for a strictly local smoke test.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=180) as response:
        result = json.load(response)
    content = result["choices"][0]["message"]["content"]
    if not content or not content.strip():
        raise ValueError("Empty model response")
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(), status="ok",
                  endpoint="http://127.0.0.1:8087/v1", model="Qwen2.5-1.5B-Instruct Q4_K_M",
                  runtime="llama.cpp b12284 win-cpu-x64", source_doc_id=doc["id"],
                  elapsed_seconds=round(time.monotonic() - start, 2), response=content,
                  usage=result.get("usage"), quality_acceptance=False)
    (DATA / "model-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
