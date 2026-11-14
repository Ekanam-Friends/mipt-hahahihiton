"""Release audit: corpus integrity, retrieval, exact-prompt replay and evidence.

Offline results do not certify fresh inference, independent human review or submission.
Run from the release root; all output paths are new E5 artifacts.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from regnav.core.ingest import load_chunks
from regnav.core.pipeline import ExtractiveReasoner, LLMReasoner, Navigator
from regnav.core.revisions import RevisionRegistry
from regnav.core.search import HybridSearcher
from verify_e3 import ReplayClient
from apply_e3_reviews import answer_digest


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(line) for line in (ROOT / path).read_text(encoding='utf-8').splitlines() if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='data/official/e5-checks/offline.json')
    args = ap.parse_args()
    started = time.perf_counter()
    data = ROOT / 'data/official'
    chunks = load_chunks(data)
    manifest = lines('data/official/manifest.jsonl')
    registry = RevisionRegistry.load(data / 'revisions.json')
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'Offline release regression; no fresh LLM, independent human or submission acceptance',
              'snapshot_downloaded_at': sorted({m['downloaded_at'] for m in manifest}),
              'implementation_sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p)
                                         for p in sorted((ROOT / 'regnav').rglob('*.py'))},
              'corpus_sha256': {p: digest(ROOT / p) for p in ['data/official/chunks.jsonl', 'data/official/manifest.jsonl', 'data/official/revisions.json']}}
    errors = []
    represented = Counter(c.doc_id for c in chunks)
    report['corpus'] = {'files': len(manifest), 'chunks': len(chunks), 'documents': []}
    for m in manifest:
        original = ROOT / m['local_path']
        ok = original.is_file() and digest(original) == m['sha256'] and represented[m['id']] > 0
        report['corpus']['documents'].append({'id': m['id'], 'title': m['title'], 'sha256_matches': ok, 'chunks': represented[m['id']]})
        if not ok:
            errors.append({'phase': 'corpus', 'id': m['id']})
    search = HybridSearcher(chunks)
    nav = Navigator(search, ExtractiveReasoner(), registry=registry)
    qs = lines('eval/e2-questions.jsonl')
    rows = []
    for q in qs:
        tick = time.perf_counter()
        hits, trace = nav.retrieve(q['question'])
        ranks = []
        for expected in q['expected']:
            ranks.append({'doc_id': expected['doc_id'],
                          'document_rank': next((i for i, h in enumerate(hits, 1) if h.chunk.doc_id == expected['doc_id']), None),
                          'fragment_rank': next((i for i, h in enumerate(hits, 1) if h.chunk.chunk_id in expected['chunk_ids']), None)})
        passed = all(r['fragment_rank'] is not None for r in ranks)
        rows.append({'id': q['id'], 'passed': passed, 'returned_k': len(hits), 'gold_ranks': ranks,
                     'elapsed_s': round(time.perf_counter() - tick, 4), 'trace': trace})
        if not passed:
            errors.append({'phase': 'retrieval', 'id': q['id']})
    all_ranks = [rank for row in rows for rank in row['gold_ranks']]
    report['retrieval'] = {'questions': len(rows), 'all_fragments_found': sum(r['passed'] for r in rows),
        'document_recall': sum(r['document_rank'] is not None for r in all_ranks) / len(all_ranks),
        'fragment_recall': sum(r['fragment_rank'] is not None for r in all_ranks) / len(all_ranks),
        'recall_at_k': {str(k): {field: sum(r[field] is not None and r[field] <= k for r in all_ranks) / len(all_ranks)
                                  for field in ['document_rank', 'fragment_rank']} for k in [1, 3, 5, 10]},
        'latency_median_s': statistics.median(r['elapsed_s'] for r in rows), 'results': rows}
    reviews = read('eval/e3-final-source-reviews.json')['reviews']
    replay_rows = []
    for path in ['data/official/e3-current-answer-report.json', 'data/official/e3-current-extra-report.json']:
        source = read(path)
        for old in source['results']:
            client = ReplayClient({'results': [old]})
            current = Navigator(search, LLMReasoner(client), registry=registry).ask(old['question'], as_of='2026-11-12').to_dict()
            same = answer_digest(current) == answer_digest(old['answer'])
            review = reviews.get(old['id'], {})
            reviewed = review.get('answer_sha256') == answer_digest(old['answer']) and all(review.get('checks', {}).values()) and bool(review.get('checks'))
            proofs = [e for item in current['summary'] + current['steps'] + current['conflicts'] for e in item['evidence']]
            row = {'id': old['id'], 'inference_mode': 'exact_prompt_replay', 'all_calls_consumed': client.position == len(client.queue),
                   'same_answer_as_reviewed': same, 'saved_source_review_matches': reviewed,
                   'expected_status': old.get('expected_status'), 'status': current['status'],
                   'status_matches': current['status'] in old['expected_status'],
                   'saved_inference_elapsed_s': old['elapsed_s'], 'evidence_count': len(proofs)}
            row['passed'] = same and reviewed and row['all_calls_consumed'] and row['status_matches']
            replay_rows.append(row)
            if not row['passed']:
                errors.append({'phase': 'replay', 'id': old['id'], 'status': current['status']})
            print(old['id'], current['status'], 'exact_reviewed_answer', same, flush=True)
    negatives = [r for r in replay_rows if r['expected_status'] == ['not_found']]
    positives = [r for r in replay_rows if 'not_found' not in r['expected_status']]
    report['generation_regression'] = {'mode': 'exact prompt replay, not new generation', 'results': replay_rows,
        'passed': sum(r['passed'] for r in replay_rows), 'total': len(replay_rows),
        'false_refusals': sum(r['status'] == 'not_found' for r in positives), 'answerable_cases': len(positives),
        'correct_refusals': sum(r['status'] == 'not_found' for r in negatives), 'negative_cases': len(negatives),
        'technical_errors': sum(r['status'] == 'error' for r in replay_rows),
        'semantic_support_and_procedure_completeness': 'Prior Codex reviews bound to unchanged full answer hashes; independent human review pending'}
    report.update(passed=not errors, errors=errors, elapsed_s=round(time.perf_counter() - started, 3),
                  independent_acceptance=False, fresh_inference_acceptance=False, submission_confirmed=False)
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['passed', 'errors', 'elapsed_s']}, ensure_ascii=False))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
