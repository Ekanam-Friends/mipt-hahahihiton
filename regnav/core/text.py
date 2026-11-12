"""Нормализация и токенизация русского текста."""
from __future__ import annotations

import re
from functools import lru_cache

import snowballstemmer

_stemmer = snowballstemmer.stemmer("russian")

STOP = set(
    """а без более бы был была были было быть в вам вас весь во вот все всего всех вы где да
    даже для до его ее если есть еще же за здесь и из или им их к как ко когда кто ли либо
    между меня мне может мы на над надо наш не него нее нет ни них но ну о об однако он она
    они оно от очень по под после при про с со так также такой там те тем то того тоже той
    только том ты у уже хотя чего чей чем что чтобы чье чья эта эти это я мфти какой какая
    какие каким нужно ли можно мой моя мои свой""".split()
)

_WORD = re.compile(r"[0-9a-zа-я]+(?:-[0-9a-zа-я]+)*")


def normalize(s: str) -> str:
    """Приводит текст к виду для сравнения: регистр, ё, кавычки, тире, пробелы."""
    s = s.lower().replace("ё", "е").replace("\xa0", " ")
    s = re.sub(r"[«»„“”\"'`]", '"', s)
    s = re.sub(r"[‐‑‒–—―−]", "-", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


@lru_cache(maxsize=200_000)
def stem(word: str) -> str:
    return _stemmer.stemWord(word)


def tokenize(s: str, *, keep_stop: bool = False) -> list[str]:
    toks = _WORD.findall(normalize(s))
    return [stem(t) for t in toks if keep_stop or t not in STOP]


def char_ngrams(s: str, n_min: int = 3, n_max: int = 5) -> list[str]:
    """Символьные n-граммы внутри слов — устойчивы к морфологии и опечаткам."""
    out = []
    for w in _WORD.findall(normalize(s)):
        if w in STOP:
            continue
        w = f" {w} "
        for n in range(n_min, n_max + 1):
            out.extend(w[i : i + n] for i in range(max(1, len(w) - n + 1)))
    return out
