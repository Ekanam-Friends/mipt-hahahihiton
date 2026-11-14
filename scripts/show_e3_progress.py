"""Inspect saved generation results without loading the search index or model."""
import argparse
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('report', nargs='?', default='data/official/e3-current-answer-report.json')
ap.add_argument('--last', type=int, default=3)
args = ap.parse_args()
report = json.loads(Path(args.report).read_text(encoding='utf-8'))
print(report['model'], report.get('created_at'))
print([(r['id'], r['answer']['status'], r.get('elapsed_s')) for r in report['results']])
for row in report['results'][-args.last:]:
    answer = row['answer']
    print('\n###', row['id'], answer['status'], 'gold cited:', row.get('all_gold_fragments_cited'))
    for claim in answer['summary']:
        print('SUMMARY:', claim['text'])
        print('EVIDENCE:', [e['chunk_id'] for e in claim['evidence']])
    for step in answer['steps']:
        print('STEP:', step['action'])
    for conflict in answer.get('conflicts', []):
        print('CONFLICT:', conflict['text'])
        print('EVIDENCE:', [e['chunk_id'] for e in conflict['evidence']])
    if answer.get('clarifying_question'):
        print('CLARIFY:', answer['clarifying_question'])
    print('GAPS:', answer['missing_information'])
    print('WARNINGS:', answer['warnings'])
    if answer.get('error_code'):
        print('ERROR:', answer['error_code'], answer.get('verification'))
