"""Run actual answer generation against the official snapshot; save failures too.

Model self-assessment is NOT human acceptance. Review saved answers against originals.
"""
import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from regnav.core.ingest import load_chunks
from regnav.core.llm import OpenAICompatClient
from regnav.core.pipeline import LLMReasoner, Navigator
from regnav.core.revisions import RevisionRegistry
from regnav.core.search import HybridSearcher


class RecordingClient:
    def __init__(self, client):
        self.client, self.calls = client, []

    def complete(self, system, user, **kwargs):
        start = time.perf_counter()
        row = {"system": system, "user": user}
        self.calls.append(row)
        try:
            row["response"] = self.client.complete(system, user, **kwargs)
            return row["response"]
        except Exception as exc:
            row["error_type"] = type(exc).__name__
            raise
        finally:
            row["elapsed_s"] = round(time.perf_counter() - start, 2)


class ReplayClient:
    """Replay actual completions only if every prompt is byte-for-byte identical."""
    def __init__(self, report):
        self.queue = [call for row in report['results'] for call in row['calls']]
        self.position, self.calls = 0, []

    def complete(self, system, user, **kwargs):
        if self.position >= len(self.queue):
            raise ValueError('Replay exhausted.')
        call = self.queue[self.position]
        if call['system'] != system or call['user'] != user:
            raise ValueError('Replay refused: model prompt changed.')
        self.position += 1
        self.calls.append(call)
        if 'error_type' in call:
            raise RuntimeError('Recorded provider error: ' + call['error_type'])
        return call['response']


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def ordered_replay(report, questions):
    """Recorded inference may have been collected in a prioritized ID order."""
    rows = {row['id']: row for row in report['results']}
    if len(rows) != len(report['results']):
        raise ValueError('Replay refused: duplicate question IDs')
    return {**report, 'results': [rows[q['id']] for q in questions if q['id'] in rows]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ids', nargs='*')
    ap.add_argument('--output', default='data/official/e3-current-answer-report.json')
    ap.add_argument('--questions', default='eval/e2-questions.jsonl')
    ap.add_argument('--model-file', default='models/qwen3-4b-instruct-2507-q4_k_m.gguf')
    ap.add_argument('--model-name', default='Qwen3-4B-Instruct-2507 Q4_K_M compact context')
    ap.add_argument('--context-tokens', type=int, default=12288)
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--retry-errors', action='store_true', help='With --resume, retry saved technical failures')
    ap.add_argument('--replay', help='Replay an actual inference report through an updated postprocessor; no model calls')
    args = ap.parse_args()
    if args.retry_errors and not args.resume:
        ap.error('--retry-errors requires --resume')
    root = Path(__file__).resolve().parents[1]
    data = root / 'data/official'
    qpath = root / args.questions
    questions = [json.loads(l) for l in qpath.read_text(encoding='utf-8').splitlines()]
    if args.ids:
        by_id = {q['id']: q for q in questions}
        if len(set(args.ids)) != len(args.ids) or any(qid not in by_id for qid in args.ids):
            ap.error('--ids must contain distinct known question IDs')
        questions = [by_id[qid] for qid in args.ids]
    manifest = [json.loads(l) for l in (data / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
    for m in manifest:
        assert hashlib.sha256((root / m['local_path']).read_bytes()).hexdigest() == m['sha256']
    replay = json.loads((root / args.replay).read_text(encoding='utf-8')) if args.replay else None
    if replay and args.ids:
        recorded = {row['id']: row for row in replay['results']}
        if any(qid not in recorded for qid in args.ids):
            ap.error('Requested replay ID has no saved answer')
        replay = {**replay, 'results': [recorded[qid] for qid in args.ids]}
    if replay:
        selected_ids = {r['id'] for r in replay['results']}
        questions = [q for q in questions if q['id'] in selected_ids]
        replay = ordered_replay(replay, questions)
    client = ReplayClient(replay) if replay else RecordingClient(OpenAICompatClient('http://127.0.0.1:8087/v1', 'EMPTY', 'regnav-local'))
    nav = Navigator(HybridSearcher(load_chunks(data)), LLMReasoner(client), registry=RevisionRegistry.load(data / 'revisions.json'))
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'corpus_downloaded_at': sorted({m['downloaded_at'] for m in manifest}),
              'gold_sha256': hashlib.sha256(qpath.read_bytes()).hexdigest(),
              'model': args.model_name, 'context_tokens': args.context_tokens,
              'quality_acceptance': False, 'scope': 'Actual local generation; human source review required', 'results': []}
    report['implementation_sha256'] = {str(p.relative_to(root)): sha256_file(p)
        for p in sorted((root / 'regnav/core').glob('*.py'))}
    report['corpus_sha256'] = {str(p.relative_to(root)): sha256_file(p)
        for p in [data / 'chunks.jsonl', data / 'manifest.jsonl', data / 'revisions.json']}
    report['model_sha256'] = sha256_file(root / args.model_file)
    if replay:
        for key in ('gold_sha256', 'model_sha256', 'context_tokens'):
            if replay[key] != report[key]:
                if key == 'gold_sha256' and args.ids:
                    by_id = {q['id']: q for q in questions}
                    if all(row['id'] in by_id and all(row[field] == by_id[row['id']][field]
                           for field in ('question', 'expected', 'required_elements')) for row in replay['results']):
                        continue
                raise ValueError('Replay refused: changed ' + key)
        report.update(inference_created_at=replay['created_at'], inference_report_sha256=sha256_file(root / args.replay),
                      inference_report_path=args.replay, inference_gold_sha256=replay['gold_sha256'],
                      inference_implementation_sha256=replay['implementation_sha256'],
                      scope='Actual recorded local completions replayed through current postprocessor; prompts must match exactly')
    output = root / args.output
    if args.resume and output.exists():
        previous = json.loads(output.read_text(encoding='utf-8'))
        for key in ('implementation_sha256', 'corpus_sha256', 'model_sha256', 'gold_sha256', 'context_tokens'):
            if previous.get(key) != report[key]:
                raise ValueError('Resume refused: changed ' + key)
        report = previous
        if report.get('inference_report_sha256'):
            report['scope'] = 'Actual local inference, with prior byte-identical completions replayed as marked per row; source review required'
            for row in report['results']:
                row.setdefault('inference_mode', 'replay')
        if args.retry_errors:
            failed = [r for r in report['results'] if r['answer']['status'] == 'error']
            report.setdefault('previous_failures', []).extend(failed)
            report['results'] = [r for r in report['results'] if r['answer']['status'] != 'error']
            report['quality_acceptance'] = False
    done = {r['id'] for r in report['results']}
    for q in questions:
        if q['id'] in done:
            continue
        client.calls = []
        started = time.perf_counter()
        answer = nav.ask(q['question'], as_of=q['as_of'])
        if replay and answer.error_code == 'provider_failed':
            raise ValueError('Replay failed; inspect prompt mismatch or recorded provider error.')
        cited = {p.chunk_id for c in answer.summary + answer.conflicts for p in c.evidence}
        cited.update(p.chunk_id for s in answer.steps for p in s.evidence)
        cited.update(e['chunk_id'] for issue in answer.applicability for e in issue.get('evidence', []))
        row = {'id': q['id'], 'question': q['question'], 'required_elements': q['required_elements'],
               'expected': q['expected'], 'answer': answer.to_dict(),
               'all_gold_fragments_cited': all(cited.intersection(e['chunk_ids']) for e in q['expected']),
               'expected_status': q.get('expected_status', ['answer', 'clarify']),
               'status_matches': answer.status in q.get('expected_status', ['answer', 'clarify']),
               'elapsed_s': round(time.perf_counter() - started, 2), 'calls': client.calls,
               'inference_mode': 'replay' if replay else 'live',
               'source_review': {'accepted': False, 'state': 'pending', 'reviewer': None}}
        report['results'].append(row)
        if replay:
            original = next(r for r in replay['results'] if r['id'] == q['id'])
            row['postprocess_elapsed_s'] = row['elapsed_s']
            row['elapsed_s'] = original['elapsed_s']
        report['statuses'] = dict(Counter(r['answer']['status'] for r in report['results']))
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(q['id'], answer.status, row['elapsed_s'], 'gold_cited', row['all_gold_fragments_cited'], flush=True)
        if answer.error_code == 'provider_failed':
            print('Provider failed; stopping instead of recording the same outage for every remaining question.', flush=True)
            return 2
    if replay and client.position != len(client.queue):
        raise ValueError('Replay refused: unused completions remain.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
