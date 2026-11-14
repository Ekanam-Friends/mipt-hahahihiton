"""Bind source-text reviews to exact saved answers. Never infer acceptance from LLM flags."""
import argparse
import hashlib
import json
from pathlib import Path


def answer_digest(answer):
    return hashlib.sha256(json.dumps(answer, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def validate_snapshot(report, root):
    """A saved answer cannot certify a different implementation or index."""
    expected_code = {str(p.relative_to(root)) for p in (root / 'regnav/core').glob('*.py')}
    if set(report.get('implementation_sha256', {})) != expected_code:
        raise ValueError('Incomplete implementation fingerprint; regenerate the report.')
    for field in ('implementation_sha256', 'corpus_sha256'):
        if not report.get(field):
            raise ValueError('Missing fingerprint: ' + field)
        for name, expected in report[field].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Snapshot changed: ' + name)
    if report.get('inference_report_path'):
        source = (root / report['inference_report_path']).resolve()
        if not source.is_relative_to(root.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest() != report.get('inference_report_sha256'):
            raise ValueError('Recorded inference provenance changed.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('report')
    ap.add_argument('--questions', required=True)
    ap.add_argument('--reviews', default='eval/e3-source-reviews.json')
    args = ap.parse_args()
    path = Path(args.report)
    report = json.loads(path.read_text(encoding='utf-8'))
    validate_snapshot(report, Path(__file__).resolve().parents[1])
    qpath = Path(args.questions)
    questions = [json.loads(line) for line in qpath.read_text(encoding='utf-8').splitlines() if line.strip()]
    reviews = json.loads(Path(args.reviews).read_text(encoding='utf-8'))
    if report['gold_sha256'] != hashlib.sha256(qpath.read_bytes()).hexdigest():
        raise ValueError('Gold set changed; cannot accept these answers.')
    expected_ids = {q['id'] for q in questions}
    actual_ids = [r['id'] for r in report['results']]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError('Duplicate answer IDs.')
    for row in report['results']:
        review = reviews.get('reviews', {}).get(row['id'])
        if not review or review['answer_sha256'] != answer_digest(row['answer']):
            row['source_review'] = {'accepted': False, 'state': 'pending', 'reviewer': None}
            continue
        checks = review['checks']
        required = {'grounding', 'required_elements', 'order', 'status', 'source_links'}
        if set(checks) != required or any(type(v) is not bool for v in checks.values()):
            raise ValueError('Review must explicitly check every criterion: ' + row['id'])
        if not review.get('notes', '').strip():
            raise ValueError('Review must record its source comparison: ' + row['id'])
        accepted = (all(checks.values()) and row['answer']['status'] != 'error'
                    and row['status_matches'] and row['all_gold_fragments_cited'])
        row['source_review'] = {**review, 'accepted': accepted, 'state': 'accepted' if accepted else 'rejected',
                                'reviewer': reviews['reviewer']}
    report['review_summary'] = {'expected': len(expected_ids), 'recorded': len(actual_ids),
        'accepted': sum(r['source_review']['accepted'] for r in report['results']),
        'pending': sum(r['source_review']['state'] == 'pending' for r in report['results']),
        'reviewer': reviews['reviewer']}
    report['quality_acceptance'] = set(actual_ids) == expected_ids and all(r['source_review']['accepted'] for r in report['results'])
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(report['review_summary'], 'quality_acceptance:', report['quality_acceptance'])
    return 0 if report['quality_acceptance'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
