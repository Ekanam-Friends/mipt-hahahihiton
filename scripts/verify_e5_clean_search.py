"""Retrieval after Linux OCR: source gold quotes, not Windows content-hash IDs."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from regnav.core.ingest import load_chunks
from regnav.core.pipeline import Navigator, ExtractiveReasoner
from regnav.core.search import HybridSearcher


def normalized(text):
    return re.sub(r'\s+', ' ', text.casefold().replace('ё', 'е')).strip()


data = Path(os.environ.get('E5_IMPORT_DIRECTORY', '/out/clean-import-fixed'))
nav = Navigator(HybridSearcher(load_chunks(data)), ExtractiveReasoner())
questions = [json.loads(line) for line in (ROOT / 'eval/e2-questions.jsonl').read_text().splitlines()]
results = []
for q in questions:
    hits, trace = nav.retrieve(q['question'])
    checks = [{'doc_id': e['doc_id'], 'quote': e['quote'],
               'found': any(h.chunk.doc_id == e['doc_id'] and normalized(e['quote']) in normalized(h.chunk.text) for h in hits)} for e in q['expected']]
    results.append({'id': q['id'], 'passed': all(e['found'] for e in checks), 'checks': checks})
report = {'created_at': datetime.now(timezone.utc).isoformat(), 'scope': 'Fresh Linux import retrieval by exact whitespace-normalized gold quote and document ID, not generation',
          'questions': len(results), 'passed': sum(r['passed'] for r in results), 'results': results}
Path('/out/clean-search.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: v for k, v in report.items() if k != 'results'}, ensure_ascii=False))
for row in results:
    if not row['passed']:
        print(row['id'], [c for c in row['checks'] if not c['found']])
raise SystemExit(int(report['passed'] != report['questions']))
