"""Check literal bindings and local anchors, separately from semantic source review."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('reports', nargs='+')
    ap.add_argument('--output', default='data/official/e3-evidence-report.json')
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    data = root / 'data/official'
    chunks = {c['chunk_id']: c for c in (json.loads(l) for l in (data / 'chunks.jsonl').read_text(encoding='utf-8').splitlines())}
    errors, html, anchors = [], {}, set()
    claims_checked = evidence_checked = 0
    for line in (data / 'manifest.jsonl').read_text(encoding='utf-8').splitlines():
        entry = json.loads(line)
        if digest(root / entry['local_path']) != entry['sha256']:
            errors.append({'source': entry['id'], 'error': 'original_sha256_changed'})
    for report_path in args.reports:
        report = json.loads((root / report_path).read_text(encoding='utf-8'))
        for row in report['results']:
            answer = row['answer']
            for item in answer['summary'] + answer['steps'] + answer['conflicts']:
                is_conflict = item in answer['conflicts']
                text = item.get('text', item.get('action'))
                claims_checked += 1
                proofs = item.get('evidence', [])
                if not proofs:
                    errors.append({'id': row['id'], 'error': 'no_evidence'})
                if not is_conflict and not any(text in p['quote'] for p in proofs):
                    errors.append({'id': row['id'], 'error': 'text_not_an_intact_source_span', 'text': text})
                for proof in proofs:
                    evidence_checked += 1
                    source = chunks.get(proof['chunk_id'])
                    if not source or proof['quote'] != source['text']:
                        errors.append({'id': row['id'], 'error': 'quote_does_not_match_source', 'chunk_id': proof['chunk_id']})
                        continue
                    if proof['doc_id'] != source['doc_id'] or proof['title'] != source['doc_title']:
                        errors.append({'id': row['id'], 'error': 'document_metadata_changed'})
                    if proof.get('url') != source['meta'].get('url') or proof.get('view_path') != source['meta'].get('view_path'):
                        errors.append({'id': row['id'], 'error': 'source_link_changed'})
                    try:
                        viewer, anchor = proof['view_path'].split('#', 1)
                        target = (root / viewer).resolve()
                        if not target.is_relative_to(root.resolve()):
                            raise ValueError('outside workspace')
                        if target not in html:
                            html[target] = target.read_text(encoding='utf-8')
                        if f'id="{anchor}"' not in html[target]:
                            raise ValueError('missing anchor')
                        anchors.add((str(target), anchor))
                    except (OSError, ValueError, AttributeError):
                        errors.append({'id': row['id'], 'error': 'invalid_local_anchor', 'chunk_id': proof['chunk_id']})
    result = {'created_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'literal text, original hashes and local anchors only; not semantic completeness',
              'reports': {p: digest(root / p) for p in args.reports},
              'chunks_sha256': digest(data / 'chunks.jsonl'), 'claims_checked': claims_checked,
              'evidence_checked': evidence_checked, 'unique_local_anchors': len(anchors),
              'passed': not errors, 'errors': errors}
    (root / args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({k: v for k, v in result.items() if k not in {'errors', 'reports', 'chunks_sha256'}})
    if errors:
        print(errors)
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
