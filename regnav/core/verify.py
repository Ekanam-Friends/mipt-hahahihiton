"""Проверка, что цитата дословно есть в тексте пункта.

«Дословно» — с точностью до регистра, ё/е, вида кавычек и тире, пробелов и переносов строк.
Многоточие внутри цитаты допускается: каждая часть должна найтись, по порядку.
"""
from __future__ import annotations

import re

from .text import normalize

MIN_QUOTE = 20  # короче — не доказательство


def _norm(s: str) -> str:
    s = re.sub(r"(\w)-\s+(\w)", r"\1\2", s)  # перенос слова, оставшийся после OCR
    return normalize(s)


def quote_in_text(quote: str, text: str) -> bool:
    q = _norm(quote).strip(' ."')
    if len(q) < MIN_QUOTE:
        return False
    t = _norm(text)
    pos = 0
    for part in re.split(r"\s*(?:\.\.\.|…)\s*", q):
        part = part.strip(' ."')
        if not part:
            continue
        i = t.find(part, pos)
        if i < 0:
            return False
        pos = i + len(part)
    return True
