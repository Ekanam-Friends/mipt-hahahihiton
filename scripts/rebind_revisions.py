"""Explicitly rebind OCR-dependent IDs by unique source quotes and original hashes.

Never guesses between multiple candidates or accepts changed original documents.
Run after an import on a different OCR platform, before starting the service.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from regnav.core.ingest import load_chunks
from regnav.core.text import normalize


def rebind(registry, chunks):
    result = copy.deepcopy(registry)
    known = {c.chunk_id: c for c in chunks}
    groups = {}
    for chunk in chunks:
        groups.setdefault(chunk.doc_id, []).append(chunk)
    for did, entry in result.get('documents', {}).items():
        candidates = groups.get(did, [])
        if not candidates or any(c.meta.get('source_sha256') != entry.get('sha256') for c in candidates):
            raise ValueError('Original hash or document mismatch: ' + did)
    proofs = [(did, proof) for did, entry in result.get('documents', {}).items() for proof in entry.get('evidence', [])]
    proofs += [(proof.get('doc_id') or proof['chunk_id'].partition('#')[0], proof)
               for conflict in result.get('conflicts', []) for proof in conflict.get('evidence', [])]
    for did, proof in proofs:
        old = known.get(proof['chunk_id'])
        quote = normalize(proof.get('quote', ''))
        if old and old.doc_id == did and quote and quote in normalize(old.text):
            continue
        matches = [c for c in groups.get(did, []) if quote and quote in normalize(c.text)]
        if len(matches) != 1:
            raise ValueError('Quote must identify exactly one chunk: ' + proof['chunk_id'])
        chunk = matches[0]
        proof.update(chunk_id=chunk.chunk_id, locator=chunk.meta.get('locator'), view_path=chunk.meta.get('view_path'))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path('data/official'))
    args = parser.parse_args()
    path = args.data / 'revisions.json'
    result = rebind(json.loads(path.read_text(encoding='utf-8')), load_chunks(args.data))
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Registry proofs validated and rebound by unique quotes; original hashes unchanged.')
