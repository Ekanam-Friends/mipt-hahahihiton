"""Гибридный поиск по пунктам документов.

Каналы:
- BM25 по стеммированным словам — номера приказов, точные термины;
- «смысловой» канал — эмбеддинги через адаптер (GigaChat Embeddings и т.п.), а пока ключей
  нет — TF-IDF по символьным n-граммам (устойчив к морфологии и ошибкам OCR).
Результаты каналов сливаются через Reciprocal Rank Fusion.

Для честного отказа считаем `coverage` — долю значимых слов запроса, найденных в пункте.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np

from .parse import Chunk
from .text import char_ngrams, tokenize


@dataclass
class Hit:
    chunk: Chunk
    score: float          # итоговый RRF-скор
    coverage: float       # доля слов запроса, найденных в пункте (0..1)
    ranks: dict           # место в каждом канале, для отладки


class SparseIndex:
    """BM25 поверх произвольной токенизации (слова или n-граммы)."""

    def __init__(self, docs: Sequence[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.len = np.array([len(d) for d in docs], dtype=float)
        self.avg = float(self.len.mean()) if self.n else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, d in enumerate(docs):
            for t, tf in Counter(d).items():
                self.postings[t].append((i, tf))
        self.idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        s = np.zeros(self.n)
        for t, qtf in Counter(query).items():
            if t not in self.postings:
                continue
            idf = self.idf[t]
            for i, tf in self.postings[t]:
                denom = tf + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
                s[i] += qtf * idf * tf * (self.k1 + 1) / denom
        return s


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


class DenseIndex:
    def __init__(self, embedder: Embedder, texts: list[str], cache: np.ndarray | None = None):
        self.embedder = embedder
        m = cache if cache is not None else embedder.embed(texts)
        self.m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)

    def scores(self, query: str) -> np.ndarray:
        q = self.embedder.embed([query])[0]
        return self.m @ (q / (np.linalg.norm(q) + 1e-9))


def _rrf(rank_lists: list[np.ndarray], k: int = 60) -> np.ndarray:
    total = np.zeros(len(rank_lists[0]))
    for ranks in rank_lists:
        total += 1.0 / (k + ranks)
    return total


def _ranks(scores: np.ndarray) -> np.ndarray:
    order = np.argsort(-scores, kind="stable")
    ranks = np.empty_like(order)
    ranks[order] = np.arange(1, len(order) + 1)
    # документы с нулевым скором не должны получать бонус от позиции
    ranks[scores <= 0] = len(order) + 1000
    return ranks


class HybridSearcher:
    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None, emb_cache: np.ndarray | None = None):
        self.chunks = chunks
        texts = [c.index_text() for c in chunks]
        self.word_tokens = [tokenize(t) for t in texts]
        self.words = SparseIndex(self.word_tokens)
        self.ngrams = SparseIndex([char_ngrams(t) for t in texts], k1=1.2, b=0.5)
        self.dense = DenseIndex(embedder, texts, emb_cache) if embedder else None
        self._token_sets = [set(t) for t in self.word_tokens]

    def coverage(self, query_tokens: list[str], i: int) -> float:
        q = set(query_tokens)
        if not q:
            return 0.0
        # вес слова = его idf: «командировка» важнее «оформить»
        w = {t: self.words.idf.get(t, 0.0) for t in q}
        tot = sum(w.values()) or 1.0
        return sum(v for t, v in w.items() if t in self._token_sets[i]) / tot

    def search(self, query: str, k: int = 10) -> list[Hit]:
        qt = tokenize(query)
        channels = {"bm25": self.words.scores(qt), "ngram": self.ngrams.scores(char_ngrams(query))}
        if self.dense:
            channels["dense"] = self.dense.scores(query)
        ranks = {name: _ranks(s) for name, s in channels.items()}
        fused = _rrf(list(ranks.values()))
        order = np.argsort(-fused)[:k]
        return [
            Hit(
                chunk=self.chunks[i],
                score=float(fused[i]),
                coverage=self.coverage(qt, i),
                ranks={n: int(r[i]) for n, r in ranks.items()},
            )
            for i in order
            if any(r[i] <= len(self.chunks) for r in ranks.values())
        ]
