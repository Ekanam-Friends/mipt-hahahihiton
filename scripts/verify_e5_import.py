"""Fresh full official import, without the prepared extraction cache or network."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from regnav.core.ingest import build_chunks, build_texts

started = time.perf_counter()
root = Path(__file__).resolve().parents[1]
source = root / 'data/official'
target = Path(os.environ.get('E5_IMPORT_DIRECTORY', '/out/clean-import'))
target.mkdir(parents=True, exist_ok=False)
(target / 'raw').mkdir()
records = [json.loads(line) for line in (source / 'manifest.jsonl').read_text().splitlines()]
for record in records:
    original = root / record['local_path']
    assert hashlib.sha256(original.read_bytes()).hexdigest() == record['sha256']
    shutil.copyfile(original, target / 'raw' / original.name)
    record['local_path'] = 'raw/' + original.name
(target / 'manifest.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records))
shutil.copyfile(source / 'ocr-corrections.json', target / 'ocr-corrections.json')
build_texts(target, workers=1, force=True)
chunks = build_chunks(target)
report = json.loads((target / 'import-report.json').read_text())
ok = report['summary']['error'] == 0 and {c.doc_id for c in chunks} == {r['id'] for r in records}
result = {'created_at': datetime.now(timezone.utc).isoformat(), 'scope': 'Fresh full official import without network or prepared text cache',
          'passed': ok, 'files': len(records), 'chunks': len(chunks), 'summary': report['summary'],
          'elapsed_s': round(time.perf_counter() - started, 2)}
target.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False), flush=True)
raise SystemExit(int(not ok))
