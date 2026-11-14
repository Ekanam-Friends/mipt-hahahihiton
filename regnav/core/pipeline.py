"""Question → evidence → structured draft → citation and entailment audit.

No provider/validation failure is represented as absence of a regulation.
Extractive mode exposes source excerpts and explicitly remains partial.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol

from .llm import LLMClient
from .search import Hit, HybridSearcher, split_query
from .revisions import RevisionRegistry
from .text import tokenize
from .grounding import (Claim, Evidence, GenerationError, SYSTEM, FORMAT, AUDIT_SYSTEM,
                        DRAFT_SCHEMA, audit_schema, normalize_audit, object_schema, TEXT_SCHEMA,
                        source_units, selected_draft, UNIT_SELECTION_TASK, PROCEDURE_CLAUSE_TASK, RANGE_ORDER_TASK, SELECTION_AUDIT,
                        PROCEDURE_RELEVANCE_TASK, ORDER_CLAUSES_TASK, FACT_RELEVANCE_TASK, BOOL_SCHEMA,
                        json_object, validate_draft, evidence, strings, string)

NOT_FOUND_MSG = (
    "В доступном снимке базы не найдено подтверждённого ответа на этот вопрос. "
    "Обратитесь в профильное подразделение (например, в Управление по работе с персоналом) "
    "или к руководителю."
)

# ------------------------------------------------------------------ модель ответа


@dataclass
class Step:
    action: str
    quote: str
    chunk_id: str
    responsible: str | None = None
    deadline: str | None = None
    documents: list[str] = field(default_factory=list)
    ref: str = ""
    url: str | None = None
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Answer:
    status: Literal["answer", "partial", "clarify", "not_found", "error"]
    question: str
    steps: list[Step] = field(default_factory=list)
    clarifying_question: str | None = None
    sources: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message: str | None = None
    dropped_steps: int = 0  # сколько шагов LLM отброшено без подтверждения
    retrieval: list[dict] = field(default_factory=list)
    applicability: list[dict] = field(default_factory=list)
    summary: list[Claim] = field(default_factory=list)
    kind: str = "fact"
    missing_information: list[str] = field(default_factory=list)
    conflicts: list[Claim] = field(default_factory=list)
    verification: dict = field(default_factory=dict)
    error_code: str | None = None
    corpus_snapshot: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ «мышление»


class Reasoner(Protocol):
    def rewrite(self, question: str, history: list[str]) -> str: ...
    def checklist(self, question: str, hits: list[Hit]) -> dict: ...


class ExtractiveReasoner:
    """Offline excerpts only. Never silently substituted for failed generation."""

    def __init__(self, min_coverage: float = 0.5, max_steps: int = 5):
        self.min_coverage = min_coverage
        self.max_steps = max_steps

    def rewrite(self, question: str, history: list[str]) -> str:
        return " ".join([*history[-2:], question])

    def is_relevant(self, question: str, hit: Hit) -> bool:
        return hit.coverage >= self.min_coverage

    def checklist(self, question: str, hits: list[Hit]) -> dict:
        steps = []
        for h in hits[: self.max_steps]:
            text = h.chunk.text
            # первая содержательная фраза пункта
            sent = re.split(r"(?<=[.;:])\s+", text)
            quote = next((s for s in sent if len(s) > 40), text[:300])[:400]
            steps.append({"action": quote, "quote": quote, "chunk_id": h.chunk.chunk_id})
        return {"status": "answer", "steps": steps}


class LLMReasoner:
    """Generation and an independent entailment/completeness pass. No silent fallback."""

    def __init__(self, client: LLMClient, max_context_chars: int = 28000, *, source_preserving: bool = True):
        self.client = client
        self.max_context_chars = max_context_chars
        self.source_preserving = source_preserving

    def rewrite(self, question: str, history: list[str]) -> str:
        if not history:
            return question
        payload = {"history": history[-6:], "question": question}
        out = json_object(self.client.complete(SYSTEM, "Перепиши последний вопрос с учётом истории. "
                          'JSON: {"query":"..."}. Данные: ' + json.dumps(payload, ensure_ascii=False),
                          response_schema=object_schema({"query": TEXT_SCHEMA})))
        return string(out.get("query"))

    def _open_procedure(self, question, hits, units, docs, context, parts):
        """Small local models judge one clause and one subquestion at a time.

        Every retrieved clause is considered; no top-1 shortcut hides a missing
        condition. Each subsequent audit sees the entire retrieved context,
        while its draft and question cover only one independent subquestion.
        """
        shared = 'Данные:\n' + json.dumps({'documents': docs, 'sources': context}, ensure_ascii=False) + '\n\nЗадание:\n'
        info = {row['chunk_id']: row for row in context}
        groups, summary_ids, step_ids, missing = [], [], [], []
        for part in parts:
            if part not in question and ' (' in part and part.endswith(')'):
                part = part.rsplit(' (', 1)[0]
            factual = bool(re.match(r'(?:.*?:\s*)?(?:кто|кому|где|когда|сколько|какие|какой|какую|какова|с какого|с какой|до какого|на какую|на какой|на основании чего)\b', part, re.I))
            ids, brief = [], []
            if factual:
                task = ('Выбери минимальный достаточный набор ID пунктов, прямо отвечающих на вопрос. '
                        'Верни JSON с unit_ids; если ответа нет, верни пустой список. Не выбирай другие темы.')
                schema = object_schema({'unit_ids': {'type': 'array', 'items': {'enum': list(units)}, 'maxItems': 3}})
                choice = json_object(self.client.complete(SYSTEM, shared + task + '\nВопрос сотрудника:\n' + json.dumps(part, ensure_ascii=False), response_schema=schema))
                ids = choice.get('unit_ids')
                if not isinstance(ids, list) or len(ids) > 3 or any(not isinstance(uid, str) or uid not in units for uid in ids):
                    raise GenerationError('Некорректный выбор исходных пунктов.')
            else:
                for uid, (text, handle) in units.items():
                    source = info[handle]
                    payload = {'question': part, 'candidate': {'id': uid, 'title': docs[source['doc_id']],
                               'location': source['location'], 'text': text}}
                    verdict = json_object(self.client.complete(SYSTEM, PROCEDURE_RELEVANCE_TASK + '\nДанные:\n' +
                                          json.dumps(payload, ensure_ascii=False),
                                          response_schema=object_schema({'relevant': BOOL_SCHEMA})))
                    if type(verdict.get('relevant')) is not bool:
                        raise GenerationError('Не проверена применимость исходного пункта.')
                    if verdict['relevant']:
                        ids.append(uid)
                # The closest directly relevant point supplies the short answer;
                # prerequisites may precede it in the separately ordered steps.
                brief = ids[:1]
                if len(ids) > 1:
                    payload = {'question': part, 'sources': [{'id': uid, 'text': units[uid][0]} for uid in ids]}
                    schema = object_schema({'unit_ids': {'type': 'array', 'items': {'enum': ids},
                                                        'minItems': len(ids), 'maxItems': len(ids)}})
                    ordered = json_object(self.client.complete(SYSTEM, ORDER_CLAUSES_TASK + '\nДанные:\n' +
                                          json.dumps(payload, ensure_ascii=False), response_schema=schema)).get('unit_ids')
                    if not isinstance(ordered, list) or len(ordered) != len(ids) or any(not isinstance(uid, str) for uid in ordered) or set(ordered) != set(ids):
                        raise GenerationError('Не подтверждена перестановка исходных пунктов.')
                    ids = ordered
            ids = list(dict.fromkeys(ids))
            brief = ids if factual else brief
            summary_ids.extend(brief)
            if not factual:
                step_ids.extend(ids)
            if not ids:
                missing.append('Не найдены сведения для части вопроса: ' + part)
            groups.append((part, brief, [] if factual else ids))
        summary_ids, step_ids = list(dict.fromkeys(summary_ids)), list(dict.fromkeys(step_ids))
        plan = {'status': 'not_found' if not summary_ids else 'partial' if missing else 'answer',
                'kind': 'procedure' if step_ids else 'fact', 'summary_units': summary_ids, 'step_units': step_ids,
                'missing_information': missing if summary_ids else [], 'clarifying_question': None}
        draft = selected_draft(plan, units)
        validate_draft(draft)
        ss = {uid: True for uid in summary_ids}
        ts = {uid: {'action': True, 'responsible': True, 'deadline': True, 'documents': []} for uid in step_ids}
        aggregate = {'complete': True, 'ordered': True, 'status_supported': True, 'missing_information': [], 'conflicts': []}
        for part, brief, steps in groups:
            part_plan = {'status': 'answer' if brief else 'not_found', 'kind': 'procedure' if steps else 'fact',
                         'summary_units': brief, 'step_units': steps, 'missing_information': [], 'clarifying_question': None}
            part_draft = selected_draft(part_plan, units)
            view = {k: part_draft[k] for k in ('status', 'kind', 'missing_information', 'clarifying_question')}
            view['summary'] = [{'unit_id': uid} for uid in brief]
            view['steps'] = [{'unit_id': uid, 'responsible': None, 'deadline': None, 'documents': []} for uid in steps]
            prompt = shared + SELECTION_AUDIT + '\nЧерновик:\n' + json.dumps(view, ensure_ascii=False)
            prompt += '\nПроверяй только этот вопрос сотрудника:\n' + json.dumps(part, ensure_ascii=False)
            if not brief:
                prompt += ('\nДля not_found status_supported=true, если в источниках нет ответа. '
                           'Отсутствие запрошенных сведений обосновывает отказ, даже когда complete=false. '
                           'Если шагов нет, ordered=true. Если ответ есть в источниках, status_supported=false.')
            verdict = normalize_audit(json_object(self.client.complete(SYSTEM, prompt, response_schema=audit_schema(part_draft))), part_draft)
            part_ss, part_ts = verdict.get('summary_supported'), verdict.get('steps_supported')
            if not isinstance(part_ss, list) or len(part_ss) != len(brief) or any(type(v) is not bool for v in part_ss):
                raise GenerationError('Неполная проверка выводов части вопроса.')
            if not isinstance(part_ts, list) or len(part_ts) != len(steps):
                raise GenerationError('Неполная проверка шагов части вопроса.')
            for uid, supported in zip(brief, part_ss):
                ss[uid] = ss[uid] and supported
            for uid, flags in zip(steps, part_ts):
                if not isinstance(flags, dict) or any(type(flags.get(k)) is not bool for k in ('action', 'responsible', 'deadline')) or flags.get('documents') != []:
                    raise GenerationError('Не проверены поля шага части вопроса.')
                for key in ('action', 'responsible', 'deadline'):
                    ts[uid][key] = ts[uid][key] and flags[key]
            for key in ('complete', 'ordered', 'status_supported'):
                if type(verdict.get(key)) is not bool:
                    raise GenerationError('Неполная проверка полноты части вопроса.')
                aggregate[key] = aggregate[key] and verdict[key]
            aggregate['missing_information'].extend(strings(verdict.get('missing_information', [])))
            if not isinstance(verdict.get('conflicts'), list):
                raise GenerationError('Некорректная проверка конфликтов части вопроса.')
            aggregate['conflicts'].extend(verdict['conflicts'])
        draft['_audit'] = {**aggregate, 'summary_supported': [ss[uid] for uid in summary_ids],
                           'steps_supported': [ts[uid] for uid in step_ids]}
        handles = {f'c{i}': hit.chunk.chunk_id for i, hit in enumerate(hits, 1)}
        by_id = {hit.chunk.chunk_id: hit.chunk for hit in hits}
        for item in draft['summary'] + draft['steps'] + draft['_audit']['conflicts']:
            for proof in item.get('evidence', []):
                cid = proof.get('chunk_id')
                proof['chunk_id'] = handles.get(cid, cid)
                if proof['chunk_id'] in by_id:
                    proof.setdefault('quote', by_id[proof['chunk_id']].text)
            evidence(item.get('evidence'), by_id)
        return draft

    def checklist(self, question: str, hits: list[Hit]) -> dict:
        # Short local handles avoid asking a small model to reproduce opaque Drive hashes.
        procedure = bool(re.search(r"пошагов|полный порядок|весь порядок|все этапы|(?:^|[?;]\s*)как\s+(?:оформить|открыть|подать|получить|начать|согласовать|скорректировать|обратиться)\b", question, re.I))
        # Keep actions and their conditions together; a short sentence must not
        # lose a maximum term or an exception from the same source clause.
        whole_clauses = procedure
        interval = re.search(r'пункт\w*\s+(\d+\.\d+(?:\.\d+)*)\s*[-–—]\s*(\d+\.\d+(?:\.\d+)*)', question, re.I)
        handles = {f"c{i}": h.chunk.chunk_id for i, h in enumerate(hits, 1)}
        docs = {h.chunk.doc_id: h.chunk.doc_title for h in hits}
        context = [{"chunk_id": f"c{i}", "doc_id": h.chunk.doc_id,
                    "location": h.chunk.clause, "text": h.chunk.text} for i, h in enumerate(hits, 1)]
        units = None
        if self.source_preserving:
            units, docs, context = source_units(hits, whole_clauses=whole_clauses)
            if not units:
                raise GenerationError('Нет достаточно полных исходных формулировок.')
        payload = json.dumps({"question": question, "documents": docs, "sources": context}, ensure_ascii=False)
        if len(payload) > self.max_context_chars:
            raise GenerationError("Контекст превышает лимит; требуется разбиение запроса.")
        prefix = "Данные:\n" + payload + "\n\nЗадание:\n"
        parts = split_query(question)
        kind = None
        if procedure:
            kind = 'procedure'
        elif all(re.match(r"(?:.*?:\s*)?(?:кто|кому|где|когда|сколько|какие|какой|какую|какова|с какого|с какой|до какого|на какую|на какой|на основании чего)\b", p, re.I) for p in parts):
            kind = 'fact'
        if kind == 'fact' and len(parts) > 1:
            # Keep the long source prefix byte-identical across subquestions
            # and the final audit, allowing local KV-cache reuse.
            prefix = 'Данные:\n' + json.dumps(
                {'documents': docs, 'sources': context, 'question': question}, ensure_ascii=False) + '\n\nЗадание:\n'
        if units:
            # One small task per independent question. The model selects evidence only;
            # it does not also invent status, gaps, roles or a new factual formulation.
            kind = kind or 'fact'
            selected, step_selected, missing = [], [], []
            mandatory = []
            if interval and whole_clauses:
                start, end = (tuple(map(int, value.split('.'))) for value in interval.groups())
                for i, hit in enumerate(hits, 1):
                    point = re.search(r'\b(\d+\.\d+(?:\.\d+)*)', hit.chunk.clause)
                    if point and start <= tuple(map(int, point[1].split('.')))[:len(start)] <= end:
                        mandatory.extend(uid for uid, (_, cid) in units.items() if cid == f'c{i}')
            if whole_clauses and not mandatory:
                return self._open_procedure(question, hits, units, docs, context, parts)
            for part in parts:
                target = part
                # E2 appends antecedents for retrieval. Keep them in the full question
                # context, but do not turn them into a second task for generation.
                if part not in question and ' (' in part and part.endswith(')'):
                    target = part.rsplit(' (', 1)[0]
                # A full composite question in the payload can override the
                # trailing selection task on small models. Isolate the actual
                # subquestion as well as the instruction; keep all evidence.
                selection_prefix = prefix
                if kind == 'fact' and len(parts) > 1:
                    selection_prefix = 'Данные:\n' + json.dumps(
                        {'documents': docs, 'sources': context, 'question': target}, ensure_ascii=False) + '\n\nЗадание:\n'
                factual_part = bool(re.match(r'(?:.*?:\s*)?(?:кто|кому|где|когда|сколько|какие|какой|какую|какова|с какого|с какой|до какого|на какую|на какой|на основании чего)\b', target, re.I))
                procedural_part = kind == 'procedure' and not factual_part
                allowed = mandatory if mandatory and procedural_part else list(units)
                selection_schema = {'type': 'array', 'items': {'enum': allowed},
                                    'maxItems': len(mandatory) if mandatory and procedural_part else 64 if procedural_part else 3}
                if mandatory and procedural_part:
                    selection_schema['minItems'] = len(mandatory)
                schema = object_schema({'unit_ids': selection_schema})
                task = PROCEDURE_CLAUSE_TASK if whole_clauses and procedural_part else UNIT_SELECTION_TASK
                if mandatory and procedural_part:
                    task = RANGE_ORDER_TASK
                choice = json_object(self.client.complete(SYSTEM, selection_prefix + task + '\nВопрос сотрудника:\n' +
                                                          json.dumps(target, ensure_ascii=False), response_schema=schema))
                ids = choice.get('unit_ids')
                if not isinstance(ids, list) or len(ids) > 64 or any(not isinstance(uid, str) or uid not in units for uid in ids):
                    raise GenerationError('Выбран несуществующий исходный текст.')
                if mandatory and procedural_part and (len(ids) != len(mandatory) or set(ids) != set(mandatory)):
                    raise GenerationError('Неполный явно заданный диапазон пунктов.')
                if not procedural_part and ids:
                    by_handle = {f'c{i}': hit.chunk for i, hit in enumerate(hits, 1)}
                    rejected = set()
                    for attempt in range(2):
                        relevant_ids = []
                        for uid in dict.fromkeys(ids):
                            text, handle = units[uid]
                            chunk = by_handle[handle]
                            candidate = {'question': target, 'candidate': {'id': uid, 'title': chunk.doc_title,
                                         'location': chunk.clause, 'text': text}}
                            # The task judges only this candidate. Retaining the
                            # source prefix allows local KV-cache reuse.
                            verdict = json_object(self.client.complete(SYSTEM, selection_prefix + FACT_RELEVANCE_TASK + '\nКандидат:\n' +
                                                  json.dumps(candidate, ensure_ascii=False),
                                                  response_schema=object_schema({'relevant': BOOL_SCHEMA})))
                            if type(verdict.get('relevant')) is not bool:
                                raise GenerationError('Не проверена уместность выбранного предложения.')
                            if verdict['relevant']:
                                relevant_ids.append(uid)
                            else:
                                rejected.add(uid)
                        ids = relevant_ids
                        remaining = [uid for uid in units if uid not in rejected]
                        if ids or attempt or not remaining:
                            break
                        retry_schema = object_schema({'unit_ids': {'type': 'array', 'items': {'enum': remaining}, 'maxItems': 3}})
                        retry = ('\nПредыдущий выбор не отвечает на этот вопрос. Отклонённые ID: ' +
                                 json.dumps(sorted(rejected)) + '. Выбери другие исходные предложения; если ответа нет, верни пустой список.')
                        ids = json_object(self.client.complete(SYSTEM, selection_prefix + UNIT_SELECTION_TASK + retry +
                                          '\nВопрос сотрудника:\n' + json.dumps(target, ensure_ascii=False),
                                          response_schema=retry_schema)).get('unit_ids')
                        if not isinstance(ids, list) or len(ids) > 3 or any(not isinstance(uid, str) or uid not in remaining for uid in ids):
                            raise GenerationError('Повторный выбор использует отклонённый или неизвестный исходный текст.')
                if not ids:
                    missing.append('Не найдены сведения для части вопроса: ' + target)
                selected.extend(ids)
                if procedural_part:
                    step_selected.extend(ids)
            selected = list(dict.fromkeys(selected))
            answered_kind = 'procedure' if step_selected else 'fact'
            plan = {'status': 'not_found' if not selected else 'partial' if missing else 'answer', 'kind': answered_kind,
                    'summary_units': selected[:1] if mandatory and step_selected else selected[:3] if step_selected else selected,
                    'step_units': list(dict.fromkeys(step_selected)),
                    'missing_information': missing if selected else [], 'clarifying_question': None}
            draft = selected_draft(plan, units)
        else:
            plan = None
            draft = json_object(self.client.complete(SYSTEM, prefix + FORMAT + '\nВопрос сотрудника:\n' +
                                                    json.dumps(question, ensure_ascii=False), response_schema=DRAFT_SCHEMA))
        validate_draft(draft)
        by_id = {h.chunk.chunk_id: h.chunk for h in hits}
        def resolve(items):
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("evidence"), list):
                    raise GenerationError("Некорректное доказательство.")
                for e in item["evidence"]:
                    if not isinstance(e, dict):
                        raise GenerationError("Некорректное доказательство.")
                    cid = string(e.get("chunk_id"))
                    e["chunk_id"] = handles.get(cid, cid)
                    chunk = by_id.get(e["chunk_id"])
                    if chunk is not None:
                        e.setdefault("quote", chunk.text)
        # Validate quotes before the audit, while retaining compact handles in its input.
        import copy
        resolved = copy.deepcopy(draft)
        resolve(resolved["summary"] + resolved["steps"])
        for item in resolved["summary"] + resolved["steps"]:
            evidence(item.get("evidence"), by_id)
        # Identical source prefix lets a local server reuse its KV cache. The audit is
        # a separate completion, sees the entire source context and gets its own schema.
        if units:
            audit_view = {k: draft.get(k) for k in ('status', 'kind', 'missing_information', 'clarifying_question')}
            audit_view['summary'] = [{'unit_id': uid} for uid in dict.fromkeys(plan['summary_units'])]
            audit_view['steps'] = [{'unit_id': uid, 'responsible': None, 'deadline': None, 'documents': []}
                                   for uid in dict.fromkeys(plan['step_units'])]
            audit_payload = prefix + SELECTION_AUDIT + '\nЧерновик:\n' + json.dumps(audit_view, ensure_ascii=False)
        else:
            audit_payload = prefix + AUDIT_SYSTEM[len(SYSTEM):] + "\nЧерновик:\n" + json.dumps(draft, ensure_ascii=False)
        audit_payload += '\nПроверяй только этот вопрос сотрудника:\n' + json.dumps(question, ensure_ascii=False)
        if draft['status'] == 'not_found':
            audit_payload += ('\nДля статуса not_found проверяется обоснованность отказа по доступным источникам. '
                              'Если источники не содержат ответа, status_supported=true, даже когда complete=false: '
                              'отсутствие запрошенных сведений как раз обосновывает not_found. '
                              'ordered=true, если шагов нет. Если ответ есть в источниках, status_supported=false.')
        if len(audit_payload) > self.max_context_chars + 12000:
            raise GenerationError("Проверяемый ответ превышает лимит контекста.")
        resolved["_audit"] = normalize_audit(json_object(self.client.complete(SYSTEM, audit_payload,
                                                    response_schema=audit_schema(draft))), draft)
        flags = resolved['_audit'].get('summary_supported')
        if (units and draft['kind'] == 'fact' and not draft['steps'] and isinstance(flags, list)
                and len(flags) == len(draft['summary']) and all(type(flag) is bool for flag in flags)
                and any(flags) and not all(flags)):
            # Completeness was checked before pruning. Verify the actual final
            # facts once more; never promote a pruned answer without this pass.
            kept = [i for i, supported in enumerate(flags) if supported]
            draft['summary'] = [draft['summary'][i] for i in kept]
            resolved['summary'] = [resolved['summary'][i] for i in kept]
            audit_view['summary'] = [audit_view['summary'][i] for i in kept]
            retry_payload = prefix + SELECTION_AUDIT + '\nЧерновик:\n' + json.dumps(audit_view, ensure_ascii=False)
            retry_payload += '\nПроверяй только этот вопрос сотрудника:\n' + json.dumps(question, ensure_ascii=False)
            retry_payload += ('\nНеподтверждённые утверждения удалены. Заново проверь оставшийся ответ по всем источникам: '
                              'complete=true только если ВСЕ запрошенные сведения сохранились; иначе complete=false и явно назови пробелы.')
            if len(retry_payload) > self.max_context_chars + 12000:
                raise GenerationError('Проверяемый ответ превышает лимит контекста.')
            resolved['_audit'] = normalize_audit(json_object(self.client.complete(SYSTEM, retry_payload,
                                                response_schema=audit_schema(draft))), draft)
            resolved['_audit'].update(rechecked_after_pruning=True, initial_summary_supported=flags,
                                      pruned_summary_count=len(flags) - len(kept))
        if isinstance(resolved["_audit"].get("conflicts"), list):
            resolve(resolved["_audit"]["conflicts"])
        return resolved


# ------------------------------------------------------------------ конвейер


def _title_family(title: str) -> frozenset:
    return frozenset(t for t in tokenize(title) if not t.isdigit())


class Navigator:
    def __init__(self, searcher: HybridSearcher, reasoner: Reasoner, k: int = 10,
                 min_top_coverage: float = 0.34, max_context: int = 6,
                 registry: RevisionRegistry | None = None):
        self.searcher = searcher
        self.reasoner = reasoner
        self.k = k
        self.min_top_coverage = min_top_coverage
        self.max_context = max_context
        self.registry = registry or RevisionRegistry()
        self.snapshot_dates = sorted({c.meta['downloaded_at'] for c in searcher.chunks if c.meta.get('downloaded_at')})
        self.source_quality = {}
        for chunk in searcher.chunks:
            missing = [cell['address'] for cell in chunk.meta.get('cells', [])
                       if cell.get('formula') and cell.get('cached_value') is None]
            if missing:
                entry = self.source_quality.setdefault(chunk.doc_id, {'missing_formula_values': 0, 'examples': []})
                entry['missing_formula_values'] += len(missing)
                if len(entry['examples']) < 3:
                    entry['examples'].append({'chunk_id': chunk.chunk_id, 'view_path': chunk.meta.get('view_path'), 'cells': missing})
        for chunk in searcher.chunks:
            entry = self.registry.documents.get(chunk.doc_id)
            if entry and entry.get("sha256") != chunk.meta.get("source_sha256"):
                raise ValueError(f"Реестр редакций не соответствует снимку: {chunk.doc_id}")

    def retrieve(self, query: str) -> tuple[list[Hit], list[dict]]:
        relevant, trace, seen = [], [], set()
        for part, hits in self.searcher.retrieve(query, self.k, self.max_context):
            if not hits or max(h.coverage for h in hits) < self.min_top_coverage:
                trace.append({"query": part, "chunk_ids": [], "status": "insufficient"})
                continue
            # Retrieval preserves candidate evidence. Generation relevance is a separate E3 check.
            selected = hits[:max(self.k, self.max_context)]
            trace.append({"query": part, "chunk_ids": [h.chunk.chunk_id for h in selected],
                          "status": "found" if selected else "insufficient"})
            for h in selected:
                if h.chunk.chunk_id not in seen:
                    seen.add(h.chunk.chunk_id)
                    relevant.append(h)
        # Date/edition clauses are mandatory context, with their source addresses intact.
        by_id = {c.chunk_id: c for c in self.searcher.chunks}
        mandatory = self.registry.evidence_for({h.chunk.doc_id for h in relevant})
        for hit in relevant:
            if hit.chunk.chunk_id in mandatory:
                hit.ranks["applicability"] = 1
        for cid in mandatory:
            if cid in by_id and cid not in seen:
                relevant.append(Hit(by_id[cid], 0.0, 1.0, {"applicability": 1}))
                seen.add(cid)
        return relevant, trace

    def _procedure_context(self, question, hits, trace):
        """For an explicit full procedure, retain the entire matched numbered section.

        This is evidence expansion, not a claim that other sections cannot apply.
        The completeness audit still has to check cross-references and exceptions.
        """
        if not re.search(r"пошаг|полный порядок|все этапы|весь порядок", question, re.I):
            return hits
        # An explicitly named order/section is a scope, not a request to combine editions.
        numbers = {re.sub(r'\s|–', lambda m: '-' if m.group() == '–' else '', n)
                   for n in re.findall(r'\b\d{2,6}\s*[-–]\s*\d+\b', question)}
        if numbers and re.search(r'приказ\w*', question, re.I):
            scoped = set()
            for c in self.searcher.chunks:
                if c.clause == 'преамбула':
                    own = re.search(r'№\s*(\d+(?:\s*[-–]\s*\d+)?)', c.text)
                    if own and re.sub(r'\s|–', lambda m: '-' if m.group() == '–' else '', own[1]) in numbers:
                        scoped.add(c.doc_id)
            if scoped and any(h.chunk.doc_id in scoped for h in hits):
                hits = [h for h in hits if h.chunk.doc_id in scoped]
                trace.append({'query': 'Явно запрошенный приказ: ' + ', '.join(sorted(numbers)),
                              'chunk_ids': [h.chunk.chunk_id for h in hits], 'status': 'found', 'scope_doc_ids': sorted(scoped)})
        interval = re.search(r'пункт\w*\s+(\d+\.\d+(?:\.\d+)*)\s*[-–—]\s*(\d+\.\d+(?:\.\d+)*)', question, re.I)
        if interval:
            start, end = (tuple(map(int, value.split('.'))) for value in interval.groups())
            if len(start) == len(end) and start[:-1] == end[:-1] and start <= end:
                doc_ids = {h.chunk.doc_id for h in hits}
                scoped_hits = []
                for chunk in self.searcher.chunks:
                    match = re.search(r'\b(\d+\.\d+(?:\.\d+)*)', chunk.clause)
                    if chunk.doc_id not in doc_ids or not match:
                        continue
                    number = tuple(map(int, match[1].split('.')))[:len(start)]
                    if start <= number <= end:
                        scoped_hits.append(Hit(chunk, 0.0, 1.0, {'procedure_section': 1}))
                if scoped_hits:
                    selected_ids = {h.chunk.chunk_id for h in scoped_hits}
                    scoped_hits.extend(h for h in hits if 'applicability' in h.ranks and h.chunk.chunk_id not in selected_ids)
                    trace.append({'query': 'Явно запрошенные пункты: ' + interval[1] + '–' + interval[2],
                                  'chunk_ids': [h.chunk.chunk_id for h in scoped_hits], 'status': 'found'})
                    return scoped_hits
        selected = {h.chunk.chunk_id: h for h in hits}
        seeds = []
        for part in trace:
            seed = next((selected[cid] for cid in part["chunk_ids"] if cid in selected
                         and re.search(r"\b\d+\.\d+", selected[cid].chunk.clause)
                         and "applicability" not in selected[cid].ranks), None)
            if seed:
                seeds.append(seed.chunk)
        for seed in seeds:
            root = re.search(r"\b(\d+)\.\d+", seed.clause).group(1)
            prefix = seed.clause[:re.search(r"\b\d+\.\d+", seed.clause).start()]
            for chunk in self.searcher.chunks:
                if chunk.doc_id == seed.doc_id and chunk.clause.startswith(prefix + root + '.'):
                    selected.setdefault(chunk.chunk_id, Hit(chunk, 0.0, 1.0, {"procedure_section": 1}))
        extra = [cid for cid in selected if cid not in {h.chunk.chunk_id for h in hits}]
        if extra:
            trace.append({"query": "Связанные пункты процедуры", "chunk_ids": extra, "status": "found"})
        return list(selected.values())

    def _generation_context(self, question, hits, trace):
        """Compact factual context with independent budgets for each subquestion.

        Retain two best body matches, three fused matches and ALL applicability
        evidence. Full procedure sections are never compacted by this policy.
        """
        if re.search(r'пошаг|полный порядок|все этапы|весь порядок', question, re.I):
            return hits
        if re.search(r'\bс\s+как(?:ой|ого)\s+(?:дат\w*|числ\w*|дня)\b', question, re.I):
            numbers = {re.sub(r'\s*[-–—]\s*', '-', n) for n in
                       re.findall(r'\b\d{2,6}\s*[-–—]\s*\d+\b', question)}
            numbers.update(re.findall(r'распоряжен\w*\s*(?:№|N)?\s*(\d+)\b', question, re.I))
            scoped = {h.chunk.doc_id for h in hits if any(
                re.search(r'(?<!\d)' + re.escape(number) + r'(?!\d)',
                          re.sub(r'\s*[-–—]\s*', '-', h.chunk.doc_title), re.I) for number in numbers)}
            if scoped:
                hits = [h for h in hits if h.chunk.doc_id in scoped]
                trace.append({'query': 'Дата явно указанного приказа или распоряжения',
                              'chunk_ids': [h.chunk.chunk_id for h in hits], 'status': 'found',
                              'scope_doc_ids': sorted(scoped)})
        by_id = {h.chunk.chunk_id: h for h in hits}
        selected = {}
        for part in trace:
            candidates = [by_id[cid] for cid in part['chunk_ids'] if cid in by_id]
            chosen = sorted(candidates, key=lambda h: h.ranks.get('content', 999999))[:2] + candidates[:3]
            part['generation_chunk_ids'] = list(dict.fromkeys(h.chunk.chunk_id for h in chosen))
            for hit in chosen:
                selected.setdefault(hit.chunk.chunk_id, hit)
        for hit in hits:
            if 'applicability' in hit.ranks:
                selected.setdefault(hit.chunk.chunk_id, hit)
        return list(selected.values())

    def ask(self, question: str, history: list[str] | None = None, as_of: str | None = None) -> Answer:
        if not isinstance(question, str) or not question.strip() or len(question) > 8000:
            return Answer("error", str(question)[:8000], message="Введите вопрос от 1 до 8000 символов.", error_code="invalid_question")
        if not self.searcher.chunks:
            return Answer('error', question, message='Индекс пуст. Выполните импорт источников.', error_code='index_empty')
        try:
            query = self.reasoner.rewrite(question, history or [])
            relevant, trace = self.retrieve(query)
            relevant = self._procedure_context(query, relevant, trace)
            if isinstance(self.reasoner, LLMReasoner) and self.reasoner.source_preserving:
                relevant = self._generation_context(query, relevant, trace)
        except Exception:
            return Answer("error", question, message="Не удалось подготовить запрос или прочитать индекс. Повторите запрос.", error_code="retrieval_failed")
        try:
            issues = self.registry.assess({h.chunk.doc_id for h in relevant}, as_of)
        except ValueError:
            return Answer("error", question, message="Некорректная дата применимости: ожидается YYYY-MM-DD.", error_code="invalid_date")
        cautions = [i["message"] for i in issues]
        for did in {h.chunk.doc_id for h in relevant}:
            quality = self.source_quality.get(did)
            if quality:
                title = next(h.chunk.doc_title for h in relevant if h.chunk.doc_id == did)
                cautions.append(f"Источник «{title}»: {quality['missing_formula_values']} формул без сохранённых результатов; значения не вычислялись.")
        common = dict(warnings=cautions, retrieval=trace, applicability=issues, corpus_snapshot=self.snapshot_dates)
        if not relevant:
            return Answer("not_found", question, message=NOT_FOUND_MSG, **common)
        if any(i["type"] in {"not_yet_effective", "expired", "conflict"} for i in issues):
            return Answer("clarify", question, clarifying_question="Уточните дату и применимую редакцию документа: " + "; ".join(cautions),
                          sources=self._sources(relevant), **common)
        if isinstance(self.reasoner, ExtractiveReasoner):
            claims = []
            for h in relevant[:self.reasoner.max_steps]:
                c = h.chunk
                claims.append(Claim(c.text, [Evidence(c.chunk_id, c.text, c.doc_id, c.doc_title,
                                    c.ref(), c.meta.get("url"), c.meta.get("view_path"))]))
            return Answer("partial", question, summary=claims, sources=self._sources(relevant),
                          missing_information=["Извлекающий режим: приведены выдержки; краткий вывод, полнота и порядок процедуры не проверены."],
                          verification={"mode": "extractive", "complete": False}, **common)
        try:
            draft = self.reasoner.checklist(query, relevant)
            validate_draft(draft)
            answer = self._ground(question, draft, relevant, common)
            return self._scope_used_evidence(self._requested_sheet(question, answer, relevant))
        except GenerationError as exc:
            return Answer("error", question, message="Ответ модели не прошёл проверку структуры, доказательств или лимита контекста. Повторите запрос или разделите его.",
                          sources=self._sources(relevant), error_code="invalid_generation", verification={"failure": str(exc)}, **common)
        except Exception:
            return Answer("error", question, message="Сервис генерации или проверки ответа недоступен. Повторите запрос.",
                          sources=self._sources(relevant), error_code="provider_failed", **common)

    @staticmethod
    def _scope_used_evidence(answer):
        """Unrelated retrieved metadata must not qualify the answer's sources."""
        used = {proof.doc_id for item in answer.summary + answer.steps + answer.conflicts for proof in item.evidence}
        if not used:
            return answer
        kept = [issue for issue in answer.applicability if used.intersection(issue['doc_ids'])]
        kept_messages = {issue['message'] for issue in kept}
        removed_messages = {issue['message'] for issue in answer.applicability} - kept_messages
        source_ids = used.union(did for issue in kept for did in issue['doc_ids'])
        removed_quality = tuple('Источник «' + source['title'] + '»:' for source in answer.sources
                                if source['doc_id'] not in source_ids)
        answer.warnings = list(dict.fromkeys(warning for warning in answer.warnings
                              if warning not in removed_messages and not warning.startswith(removed_quality)))
        answer.applicability = kept
        answer.sources = [source for source in answer.sources if source['doc_id'] in source_ids]
        return answer

    @staticmethod
    def _requested_sheet(question, answer, hits):
        """A proof on another worksheet must not silently answer a named locator."""
        match = re.search(r'\bна\s+листе\s+(?:[«"]([^»"]+)[»"]|([\w.-]+))', question, re.I)
        if not match or answer.status not in {'answer', 'partial'}:
            return answer
        requested = (match[1] or match[2]).strip().rstrip('.?')
        by_id = {hit.chunk.chunk_id: hit.chunk for hit in hits}
        sheets = {by_id[proof.chunk_id].meta['sheet']
                  for claim in answer.summary + answer.steps for proof in claim.evidence
                  if proof.chunk_id in by_id and by_id[proof.chunk_id].meta.get('sheet')}
        if not sheets or requested.casefold() in {sheet.casefold() for sheet in sheets}:
            return answer
        found = ', '.join('«' + sheet + '»' for sheet in sorted(sheets))
        answer.verification['model_status'] = answer.status
        answer.verification['model_complete'] = answer.verification.get('complete')
        answer.verification['complete'] = False
        answer.verification['requested_locator_supported'] = False
        answer.status = 'clarify'
        answer.clarifying_question = (f'В вопросе указан лист «{requested}», а найденные подтверждённые '
                                     f'фрагменты относятся к листам {found}. Уточните нужный лист.')
        answer.missing_information.append('Не подтверждён ответ для явно указанного листа «' + requested + '».')
        return answer

    def _ground(self, question, draft, hits, common):
        by_id = {h.chunk.chunk_id: h.chunk for h in hits}
        audit = draft.get("_audit")
        if not isinstance(audit, dict):
            raise GenerationError("Нет независимой проверки.")
        ss, ts = audit.get("summary_supported"), audit.get("steps_supported")
        if not isinstance(ss, list) or len(ss) != len(draft["summary"]) or any(type(v) is not bool for v in ss):
            raise GenerationError("Неполная проверка выводов.")
        if not isinstance(ts, list) or len(ts) != len(draft["steps"]):
            raise GenerationError("Неполная проверка шагов.")
        for key in ("complete", "ordered", "status_supported"):
            if type(audit.get(key)) is not bool:
                raise GenerationError("Некорректная проверка полноты.")
        missing = strings(draft.get("missing_information", [])) + strings(audit.get("missing_information", []))
        summary, steps, conflicts, dropped = [], [], [], 0
        for item, supported in zip(draft["summary"], ss):
            proof = evidence(item.get("evidence"), by_id)
            if supported:
                summary.append(Claim(item["text"], proof))
            else:
                dropped += 1
        for item, verdict in zip(draft["steps"], ts):
            proof = evidence(item.get("evidence"), by_id)
            if not isinstance(verdict, dict):
                raise GenerationError("Некорректная проверка шага.")
            flags = [verdict.get(k) for k in ("action", "responsible", "deadline")]
            docs = verdict.get("documents")
            if any(type(v) is not bool for v in flags) or not isinstance(docs, list) or len(docs) != len(item.get("documents", [])) or any(type(v) is not bool for v in docs):
                raise GenerationError("Не проверены поля шага.")
            if not all(flags + docs):
                dropped += 1
                continue
            first = proof[0]
            steps.append(Step(item["action"], first.quote, first.chunk_id, item.get("responsible"),
                              item.get("deadline"), item.get("documents", []), first.ref, first.url, proof))
        raw_conflicts = audit.get("conflicts")
        if not isinstance(raw_conflicts, list) or len(raw_conflicts) > 20:
            raise GenerationError("Некорректная проверка конфликтов.")
        for item in raw_conflicts:
            if not isinstance(item, dict):
                raise GenerationError("Некорректный конфликт.")
            proof = evidence(item.get("evidence"), by_id)
            if len({p.chunk_id for p in proof}) < 2:
                raise GenerationError("У конфликта нет двух сторон.")
            string(item.get("text"))  # Validate the wire field, but do not publish a new model-written fact.
            conflicts.append(Claim("Возможное расхождение: сопоставьте приведённые фрагменты и уточните применимую норму.", proof))
        if dropped:
            missing.append(f"Исключено неподтверждённых утверждений/шагов: {dropped}.")
        if not audit["ordered"]:
            steps = []
            missing.append("Последовательность действий не подтверждена; шаги не показаны.")
        incomplete = (missing or dropped or not audit["complete"] or not audit["ordered"] or
                      not audit["status_supported"] or any(p["status"] == "insufficient" for p in common["retrieval"]))
        status = draft["status"]
        used_docs = {proof.doc_id for claim in summary for proof in claim.evidence}
        used_docs.update(proof.doc_id for step in steps for proof in step.evidence)
        uncertain_comparison = any(
            issue['type'] == 'possible_conflict'
            and len(used_docs.intersection(issue['doc_ids'])) >= 2
            and any(self.registry.documents.get(did, {}).get('uncertainty')
                    for did in used_docs.intersection(issue['doc_ids']))
            for issue in common['applicability'])
        if uncertain_comparison:
            audit['applicability_requires_clarification'] = True
        if conflicts or uncertain_comparison:
            status = "clarify"
        elif status in {"not_found", "clarify"} and (dropped or not audit["status_supported"]):
            raise GenerationError("Отказ или уточнение не подтверждены.")
        elif status in {"answer", "partial"}:
            if not summary:
                raise GenerationError("Все выводы отклонены.")
            status = "partial" if incomplete or status == "partial" else "answer"
        if status == "partial" and not missing:
            missing.append("Полнота ответа или порядок действий не подтверждены проверкой.")
        used_ids = {p.chunk_id for c in summary + conflicts for p in c.evidence}
        used_ids.update(p.chunk_id for s in steps for p in s.evidence)
        issue_docs = {did for issue in common["applicability"] for did in issue["doc_ids"]}
        source_hits = [h for h in hits if h.chunk.chunk_id in used_ids or h.chunk.doc_id in issue_docs] if used_ids else hits
        return Answer(status, question, summary=summary, steps=steps, kind=draft["kind"],
                      clarifying_question=(draft.get("clarifying_question") or "Уточните применимую норму после сопоставления приведённых фрагментов.") if status == "clarify" else None,
                      sources=self._sources(source_hits), conflicts=conflicts,
                      missing_information=list(dict.fromkeys(missing)), dropped_steps=dropped,
                      message=NOT_FOUND_MSG if status == "not_found" else None,
                      verification={"mode": "llm_entailment", **audit,
                                    "conflicts": [{"text": c.text, "evidence": [{"chunk_id": e.chunk_id, "quote": e.quote}
                                                   for e in c.evidence]} for c in conflicts]}, **common)

    def _sources(self, hits: list[Hit]) -> list[dict]:
        seen, out = set(), []
        for h in hits:
            c = h.chunk
            if c.doc_id in seen:
                continue
            seen.add(c.doc_id)
            out.append({"doc_id": c.doc_id, "title": c.doc_title, "url": c.meta.get("url"),
                        "uploaded_at": c.meta.get("uploaded_at"), "view_path": c.meta.get("view_path"),
                        "downloaded_at": c.meta.get("downloaded_at"), "sha256": c.meta.get("source_sha256"),
                        "quality": self.source_quality.get(c.doc_id)})
        return out

    @staticmethod
    def _version_warnings(used, relevant: list[Hit]) -> list[str]:
        """Похожие по названию документы среди найденных → возможно, несколько редакций."""
        docs = {}
        for h in relevant:
            docs.setdefault(h.chunk.doc_id, h.chunk.doc_title)
        used_ids = {c.doc_id for c in used}
        out, seen = [], set()
        for a in sorted(used_ids):
            fa = _title_family(docs[a])
            for b, tb in docs.items():
                pair = frozenset((a, b))
                if b == a or pair in seen:
                    continue
                fb = _title_family(tb)
                if fa and fb and len(fa & fb) / len(fa | fb) >= 0.6:
                    seen.add(pair)
                    out.append(f"Найдено несколько редакций: «{docs[a]}» и «{tb}». Проверьте, какая действует.")
        return out
