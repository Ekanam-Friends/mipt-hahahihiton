"""New wording with source expectations frozen before fresh server inference.

These are author-created follow-up questions, not an independent human test set.
"""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
by_id = {q['id']: q for q in (json.loads(line) for line in (root / 'eval/e2-questions.jsonl').read_text(encoding='utf-8').splitlines())}
wording = {
    'support': 'Куда сотруднику направить обращение в первую линию УИТ? Назови официальные каналы.',
    'datacenter': 'Мне нужен виртуальный сервер в центре обработки данных. Через какую систему подать заявку и какой предельный срок указать?',
    'borrowing': 'Какая заявка нужна для внутреннего заимствования средств и как её оформить?',
    'fls-conflict': 'Каким из приказов, 460-1 или 3065-1, руководствоваться при открытии финансового лицевого счёта?',
    'structure-xlsx': 'Где в Excel-приложении приведена финансовая структура университета на 2026 год?',
}
questions = [{**by_id[key], 'id': 'e5-new-' + key, 'question': question,
              'origin': 'Author-created paraphrase with reused source gold; not independent human review'} for key, question in wording.items()]
questions += [json.loads(line) for line in (root / 'eval/e3-questions.jsonl').read_text(encoding='utf-8').splitlines() if json.loads(line)['id'] == 'negative-mortgage']
(root / 'eval/e5-questions.jsonl').write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in questions), encoding='utf-8')
print(len(questions), 'new server smoke scenarios')
