"""Vector index for historical retrieval (REQ-019, STORY-013).

VectorIndex is the interface the retrieval code depends on; the LanceDB
implementation (files under the git-ignored data/vector_index/, never SQL
Server) and the in-memory one used by tests both implement it.

Contract:
- upsert() is idempotent, keyed on case_id: indexing a case again replaces
  its entry, it never adds a second one.
- search() returns at most k cases, all from the requested Stress Test,
  most similar first. The Stress Test filter is applied before ranking, so a
  close match from another Stress Test can never take a place in the top k.
- An index that cannot be read or written raises VectorIndexError; the caller
  turns it into a visible 'unavailable' result instead of failing the review.
"""
import math
import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.models import MAX_HISTORY_CASES, HistoricalCase, SimilarCase


class VectorIndexError(Exception):
    error_class = "VectorIndexUnavailable"


class IndexedCase(BaseModel):
    """A historical case together with the embedding of its submission."""
    model_config = ConfigDict(extra="forbid")

    case: HistoricalCase
    vector: List[float] = Field(min_length=1)


def check_k(k: int) -> None:
    if not 1 <= k <= MAX_HISTORY_CASES:
        raise ValueError(f"k must be between 1 and {MAX_HISTORY_CASES}, got {k}")


class VectorIndex(ABC):
    @abstractmethod
    def upsert(self, entries: Sequence[IndexedCase]) -> None:
        ...

    @abstractmethod
    def search(self, stress_test_id: str, vector: Sequence[float], k: int) -> List[SimilarCase]:
        ...

    @abstractmethod
    def count(self, stress_test_id: str) -> int:
        """Cases indexed for one Stress Test."""


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector length {len(a)} does not match {len(b)}")
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0.0:
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / norm))


class InMemoryVectorIndex(VectorIndex):
    """For tests and demos: same contract, nothing persisted."""

    def __init__(self) -> None:
        self._entries: Dict[str, IndexedCase] = {}
        self._lock = threading.Lock()

    def upsert(self, entries: Sequence[IndexedCase]) -> None:
        with self._lock:
            for entry in entries:
                self._entries[entry.case.case_id] = entry

    def search(self, stress_test_id: str, vector: Sequence[float], k: int) -> List[SimilarCase]:
        check_k(k)
        with self._lock:
            same_test = [e for e in self._entries.values() if e.case.stress_test_id == stress_test_id]
        scored = [
            SimilarCase(**e.case.model_dump(), similarity=cosine(vector, e.vector)) for e in same_test
        ]
        scored.sort(key=lambda case: (-case.similarity, case.case_id))  # ties: stable, deterministic
        return scored[:k]

    def count(self, stress_test_id: str) -> int:
        with self._lock:
            return sum(1 for e in self._entries.values() if e.case.stress_test_id == stress_test_id)
