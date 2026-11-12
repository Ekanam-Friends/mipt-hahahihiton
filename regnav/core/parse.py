"""Разбор документа на пункты по его собственной структуре.

Документ режем не на куски фиксированной длины, а по нумерации пунктов («3.2.», «3.2.1»),
разделам («Раздел II», «Глава 3», «III. ОБЩИЕ ПОЛОЖЕНИЯ») и приложениям. Поэтому ссылка
в ответе указывает на конкретный пункт.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Chunk:
    chunk_id: str          # уникальный id: <doc_id>#<порядковый номер>
    doc_id: str
    doc_title: str
    clause: str            # «3.2», «III», «преамбула», «прил. 1, п. 2.1»
    heading: str           # заголовки родительских разделов через « / »
    text: str
    page: int | None = None
    meta: dict = field(default_factory=dict)

    def ref(self) -> str:
        c = self.clause
        if c and c[0].isdigit():
            c = "п. " + c
        return f"{self.doc_title}, {c}" if c else self.doc_title

    def index_text(self) -> str:
        """Текст для поиска: заголовки разделов + сам пункт."""
        return f"{self.doc_title}. {self.heading}. {self.text}"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- извлечение текста


def extract_pages(path: str | Path) -> list[str]:
    """Совместимый текстовый интерфейс; Office возвращается в порядке блоков."""
    from .extract import extract
    return [block["text"] for block in extract(Path(path))["blocks"]]


# ---------------------------------------------------------------- структура

# «3.», «3.2.», «3.2.1», «3.2.1.» в начале строки. Первый компонент ≤ 2 цифр,
# глубина ≤ 4 — чтобы не путать с датами (25.05.2017) и суммами.
RE_NUM = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\.?(?:\)|\s|$)\s*(.*)$")
RE_ROMAN = re.compile(r"^\s*([IVXL]{1,6})\.\s+(\S.*)$")
RE_SECTION = re.compile(r"^\s*(Раздел|РАЗДЕЛ|Глава|ГЛАВА|Статья|СТАТЬЯ)\s+([IVXL\d]+)\.?\s*(.*)$")
RE_APPENDIX = re.compile(r"^\s*(Приложение|ПРИЛОЖЕНИЕ)\s*(?:№\s*)?(\d+[а-яА-Яa-zA-Z]?)?\b(.*)$")
RE_DATE_LIKE = re.compile(r"^\s*\d{1,2}\.\d{1,2}\.\d{2,4}")

MAX_CHUNK = 1800  # символов; длинный пункт режем по абзацам


def _clean_lines(pages: list[str], preserve_numeric: bool = False) -> list[tuple[str, int]]:
    out = []
    for pno, page in enumerate(pages, 1):
        for line in page.splitlines():
            line = line.replace("\xa0", " ").rstrip()
            s = line.strip()
            if not s:
                out.append(("", pno))
                continue
            # A bare number may be table data. Only discard explicitly labelled page footers.
            if not preserve_numeric and re.fullmatch(r"(стр\.|страница)\s*\d+", s, re.I):
                continue
            out.append((line, pno))
    return out


def _join(lines: list[str]) -> str:
    text = "\n".join(lines)
    text = re.sub(r"(\w)[-‐]\n(\w)", r"\1\2", text)      # перенос слова
    text = re.sub(r"\n(?=[a-zа-яё0-9(,;«\"])", " ", text)  # строка продолжает предложение
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _is_parent(parent: str, child: str) -> bool:
    return child.startswith(parent + ".")


def split_document(pages: list[str], doc_id: str, doc_title: str, meta: dict | None = None,
                   preserve_numeric: bool = False) -> list[Chunk]:
    lines = _clean_lines(pages, preserve_numeric)
    chunks: list[Chunk] = []

    appendix = ""            # «прил. 1» — нумерация в приложении начинается заново
    roman = ""               # текущий раздел римской цифрой / «Раздел N»
    headings: dict[str, str] = {}  # номер пункта → его текст (для заголовков подпунктов)
    roman_title = ""

    cur_clause, cur_lines, cur_page = "преамбула", [], 1
    cur_end = 1
    last_num: list[int] = []

    def flush():
        nonlocal cur_lines
        text = _join(cur_lines)
        cur_lines = []
        if not text:
            return
        clause = cur_clause
        if appendix and clause != "преамбула":
            clause = f"{appendix}, п. {clause}" if clause[0].isdigit() else f"{appendix}, {clause}"
        elif appendix:
            clause = appendix
        # заголовок = римский раздел + тексты родительских пунктов
        parents = [headings[k] for k in sorted(headings, key=len) if _is_parent(k, cur_clause)]
        heading = " / ".join(x for x in [roman_title, *parents] if x)
        parts = _split_long(text)
        for i, part in enumerate(parts):
            chunks.append(
                Chunk(
                    chunk_id=f"{doc_id}#{len(chunks)}",
                    doc_id=doc_id,
                    doc_title=doc_title,
                    clause=clause if len(parts) == 1 else f"{clause} (ч. {i + 1})",
                    heading=heading[:300],
                    text=part,
                    page=cur_page,
                    meta={**(meta or {}), "source_start": cur_page, "source_end": cur_end},
                )
            )

    def plausible_next(num: str) -> bool:
        """Номер пункта должен продолжать нумерацию, иначе это число в тексте."""
        parts = [int(x) for x in num.split(".")]
        if not last_num:
            return parts[0] <= 3 and all(p <= 3 for p in parts[1:])
        # следующий на любом уровне: 3.2 → 3.3, 3.2.1, 4, 4.1
        for depth in range(len(last_num), 0, -1):
            prefix = last_num[: depth - 1]
            if parts[: depth - 1] == prefix and len(parts) >= depth:
                nxt = parts[depth - 1]
                if nxt == last_num[depth - 1] + 1 and all(p == 1 for p in parts[depth:]):
                    return True
        if parts[: len(last_num)] == last_num and len(parts) == len(last_num) + 1 and parts[-1] == 1:
            return True
        return False

    for line, pno in lines:
        s = line.strip()
        if not s:
            cur_lines.append("")
            continue

        m = RE_APPENDIX.match(s)
        if m and len(s) < 120 and (m.group(3).strip() == "" or m.group(3).strip().startswith(("к", "К"))):
            flush()
            appendix = "прил." + (f" {m.group(2)}" if m.group(2) else "")
            cur_clause, cur_page, last_num, headings, roman_title = "текст", pno, [], {}, ""
            cur_lines.append(s)
            cur_end = pno
            continue

        m = RE_SECTION.match(s) or RE_ROMAN.match(s)
        if m and len(s) < 200:
            flush()
            g = m.groups()
            if len(g) == 3:  # Раздел/Глава N Заголовок
                roman = f"{g[0].lower()} {g[1]}"
                roman_title = f"{g[0]} {g[1]}. {g[2]}".strip(". ")
            else:
                roman = g[0]
                roman_title = f"{g[0]}. {g[1]}"
            cur_clause, cur_page = roman, pno
            cur_lines.append(s)
            cur_end = pno
            continue

        m = RE_NUM.match(s)
        if m and not RE_DATE_LIKE.match(s) and plausible_next(m.group(1)):
            flush()
            num = m.group(1)
            last_num = [int(x) for x in num.split(".")]
            body = m.group(2).strip()
            headings = {k: v for k, v in headings.items() if _is_parent(k, num)}
            if body and len(body) < 150 and not body.endswith((".", ";", ":")):
                headings[num] = body.rstrip(".")
            cur_clause, cur_page = num, pno
            cur_lines.append(s)
            cur_end = pno
            continue

        if not cur_lines:
            cur_page = pno
        cur_lines.append(line)
        cur_end = pno

    flush()
    return chunks


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK:
        return [text]
    parts, buf = [], ""
    for para in re.split(r"(?<=[.;:])\s+(?=[А-ЯA-Z0-9«-])|\n", text):
        if buf and len(buf) + len(para) > MAX_CHUNK:
            parts.append(buf.strip())
            buf = ""
        buf += para + " "
    if buf.strip():
        parts.append(buf.strip())
    return parts
