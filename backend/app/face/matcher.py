"""In-memory vector index over decrypted embeddings.

* Exact cosine similarity (rows are L2-normalised -> dot product).
* Several embeddings per student: the student score is the MAX over its rows
  (np.maximum.reduceat over contiguous, PRN-sorted rows).
* Optional FAISS IndexFlatIP for large galleries without a candidate filter.
* Group photos use the Hungarian algorithm so two faces can never be
  assigned to the same student.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

logger = logging.getLogger(__name__)

try:  # optional dependency
    import faiss  # type: ignore

    HAS_FAISS = True
except Exception:  # noqa: BLE001
    faiss = None
    HAS_FAISS = False

FAISS_MIN_ROWS = 2000


@dataclass(frozen=True)
class Candidate:
    prn: str
    score: float


class EmbeddingIndex:
    def __init__(self, backend: str = "auto") -> None:
        self._lock = threading.RLock()
        self.backend_pref = backend
        self.version: int = -1
        self.model: str | None = None
        self._labels = np.array([], dtype=object)
        self._matrix = np.zeros((0, 0), dtype=np.float32)
        self._unique: list[str] = []
        self._starts = np.zeros(0, dtype=np.int64)
        self._faiss = None

    # ------------------------------------------------------------- build
    def build(self, items: Sequence[tuple[str, np.ndarray]], version: int, model: str | None) -> None:
        with self._lock:
            if not items:
                self._labels = np.array([], dtype=object)
                self._matrix = np.zeros((0, 0), dtype=np.float32)
                self._unique, self._starts, self._faiss = [], np.zeros(0, dtype=np.int64), None
            else:
                ordered = sorted(items, key=lambda it: it[0])
                labels = np.array([p for p, _ in ordered], dtype=object)
                matrix = np.stack([np.asarray(v, dtype=np.float32).ravel() for _, v in ordered])
                norms = np.linalg.norm(matrix, axis=1, keepdims=True)
                matrix = matrix / np.where(norms == 0, 1, norms)
                change = np.ones(len(labels), dtype=bool)
                change[1:] = labels[1:] != labels[:-1]
                self._labels, self._matrix = labels, np.ascontiguousarray(matrix)
                self._starts = np.flatnonzero(change).astype(np.int64)
                self._unique = [str(labels[i]) for i in self._starts]
                self._faiss = None
                if self._use_faiss():
                    index = faiss.IndexFlatIP(self._matrix.shape[1])
                    index.add(self._matrix)
                    self._faiss = index
            self.version, self.model = version, model
            logger.info("Vector index built: %d embeddings / %d students (v%s, faiss=%s)",
                        self.size, self.student_count, version, self._faiss is not None)

    def _use_faiss(self) -> bool:
        if not HAS_FAISS or self.backend_pref == "numpy":
            return False
        return self.backend_pref == "faiss" or len(self._labels) >= FAISS_MIN_ROWS

    # ------------------------------------------------------------ stats
    @property
    def size(self) -> int:
        return int(len(self._labels))

    @property
    def student_count(self) -> int:
        return len(self._unique)

    @property
    def backend(self) -> str:
        return "faiss" if self._faiss is not None else "numpy"

    def has(self, prn: str) -> bool:
        with self._lock:
            return prn in set(self._unique)

    # ----------------------------------------------------------- search
    def per_student_scores(self, queries: np.ndarray,
                           candidates: Iterable[str] | None = None) -> tuple[np.ndarray, list[str]]:
        """Return (Q x P) max-cosine matrix and the P student labels."""
        q = np.atleast_2d(np.asarray(queries, dtype=np.float32))
        with self._lock:
            if self.size == 0:
                return np.zeros((q.shape[0], 0), dtype=np.float32), []
            labels, matrix = self._labels, self._matrix
            if candidates is not None:
                wanted = set(candidates)
                mask = np.fromiter((lbl in wanted for lbl in labels), dtype=bool, count=len(labels))
                if not mask.any():
                    return np.zeros((q.shape[0], 0), dtype=np.float32), []
                labels, matrix = labels[mask], matrix[mask]
                change = np.ones(len(labels), dtype=bool)
                change[1:] = labels[1:] != labels[:-1]
                starts = np.flatnonzero(change)
            else:
                starts = self._starts
            if q.shape[1] != matrix.shape[1]:
                raise ValueError(f"Embedding dimension mismatch: query {q.shape[1]} vs index {matrix.shape[1]}")
            sims = q @ matrix.T
            per_student = np.maximum.reduceat(sims, starts, axis=1)
            return per_student, [str(labels[i]) for i in starts]

    def top_k(self, query: np.ndarray, k: int = 3, candidates: Iterable[str] | None = None,
              exclude: str | None = None) -> list[Candidate]:
        query = np.asarray(query, dtype=np.float32).ravel()
        if candidates is None and self._faiss is not None and exclude is None:
            return self._faiss_top_k(query, k)
        scores, labels = self.per_student_scores(query[None, :], candidates)
        if not labels:
            return []
        row = scores[0]
        order = np.argsort(-row)
        out: list[Candidate] = []
        for idx in order:
            if labels[idx] == exclude:
                continue
            out.append(Candidate(labels[idx], float(row[idx])))
            if len(out) >= k:
                break
        return out

    def _faiss_top_k(self, query: np.ndarray, k: int) -> list[Candidate]:
        with self._lock:
            fetch = min(self.size, max(k * 20, 50))
            sims, idx = self._faiss.search(query[None, :], fetch)
            best: dict[str, float] = {}
            for s, i in zip(sims[0], idx[0]):
                if i < 0:
                    continue
                prn = str(self._labels[i])
                if prn not in best or s > best[prn]:
                    best[prn] = float(s)
        return [Candidate(p, s) for p, s in sorted(best.items(), key=lambda kv: -kv[1])[:k]]


def assign_unique(scores: np.ndarray, labels: list[str], min_score: float) -> dict[int, tuple[str, float]]:
    """Hungarian assignment of faces (rows) to students (cols) maximising similarity."""
    if scores.size == 0 or not labels:
        return {}
    big = 1e6
    cost = -scores.astype(np.float64)
    invalid = scores < min_score
    cost[invalid] = big
    rows, cols = linear_sum_assignment(cost)
    result: dict[int, tuple[str, float]] = {}
    for r, c in zip(rows, cols):
        if not invalid[r, c]:
            result[int(r)] = (labels[int(c)], float(scores[r, c]))
    return result


def classify(score: float | None, threshold: float, margin: float) -> str:
    """MATCHED >= T+m > LOW_CONFIDENCE >= T > POSSIBLE >= T-m > UNKNOWN."""
    if score is None:
        return "UNKNOWN"
    if score >= threshold + margin:
        return "MATCHED"
    if score >= threshold:
        return "LOW_CONFIDENCE"
    if score >= threshold - margin:
        return "POSSIBLE"
    return "UNKNOWN"
