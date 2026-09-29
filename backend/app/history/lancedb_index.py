"""LanceDB implementation of VectorIndex (STORY-013).

An embedded vector database: files under the git-ignored data/vector_index/
(it holds student submissions and reviewer feedback), no server, and never
SQL Server, which stays read-only. One table, 'historical_cases'.

- upsert(): merge on case_id, so indexing the same case twice replaces its
  row and never adds a second one.
- search(): prefilter on stress_test_id, then rank by cosine distance, so
  only the requested Stress Test competes for the top k. stress_test_id is
  checked against ^ST[0-9]$ before it goes into the filter expression.
- An index that was never built (no table) is reported as VectorIndexError,
  not as "no similar cases": an unbuilt index is a setup problem the reviewer
  should see. A built index with no cases for the Stress Test returns [].
- Every call is bounded (timeout x attempts, see bounded.py); any failure of
  LanceDB, or a stored row that no longer fits HistoricalCase, surfaces as
  VectorIndexError.
"""
import re
import threading
from pathlib import Path
from typing import Any, List, Sequence

from app.history.bounded import bounded_call
from app.history.vector_index import IndexedCase, VectorIndex, VectorIndexError, check_k
from app.models import SimilarCase

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "vector_index"
TABLE = "historical_cases"
_STRESS_TEST_ID = re.compile(r"^ST[0-9]$")
_CASE_FIELDS = ("case_id", "stress_test_id", "submission_excerpt", "reviewer_feedback")


def _has_table(db: Any) -> bool:
    # list_tables() is paginated; this database holds a single table, so the
    # first page always contains it when it exists.
    return TABLE in db.list_tables().tables


def _checked(stress_test_id: str) -> str:
    if not _STRESS_TEST_ID.match(stress_test_id):
        raise ValueError(f"not a Stress Test id: {stress_test_id!r}")
    return stress_test_id


class LanceDbVectorIndex(VectorIndex):
    def __init__(self, path: Path = DEFAULT_DIR, timeout_s: float = 10.0, attempts: int = 3,
                 backoff_s: float = 0.5) -> None:
        self._path = path
        self._timeout_s = timeout_s
        self._attempts = attempts
        self._backoff_s = backoff_s
        self._write_lock = threading.Lock()  # one creator/merger per process

    def _bounded(self, fn: Any, what: str) -> Any:
        # An unbuilt index (VectorIndexError from _table) is permanent: not retried.
        return bounded_call(fn, what=what, error=VectorIndexError, timeout_s=self._timeout_s,
                            attempts=self._attempts, backoff_s=self._backoff_s,
                            no_retry=(VectorIndexError,))

    def _db(self) -> Any:
        import lancedb  # imported here: heavy, and not needed by most tests

        return lancedb.connect(str(self._path))

    def _table(self) -> Any:
        db = self._db()
        if not _has_table(db):
            # No path in the message: it reaches the reviewer (see build_history_index.py for the folder).
            raise VectorIndexError("the vector index has not been built yet")
        return db.open_table(TABLE)

    def upsert(self, entries: Sequence[IndexedCase]) -> None:
        if not entries:
            return
        rows = [{**entry.case.model_dump(), "vector": entry.vector} for entry in entries]

        def write() -> None:
            db = self._db()
            if not _has_table(db):
                db.create_table(TABLE, data=rows[:1])
            db.open_table(TABLE).merge_insert("case_id").when_matched_update_all() \
                .when_not_matched_insert_all().execute(rows)

        with self._write_lock:
            self._bounded(write, "vector index write")

    def search(self, stress_test_id: str, vector: Sequence[float], k: int) -> List[SimilarCase]:
        check_k(k)
        where = f"stress_test_id = '{_checked(stress_test_id)}'"

        def read() -> List[dict]:
            return self._table().search(list(vector)).distance_type("cosine") \
                .where(where, prefilter=True).limit(k).to_list()

        hits = self._bounded(read, "vector index search")
        try:
            cases = [
                SimilarCase(**{field: hit[field] for field in _CASE_FIELDS},
                            similarity=max(-1.0, min(1.0, 1.0 - float(hit["_distance"]))))
                for hit in hits
            ]
        except (KeyError, TypeError, ValueError) as exc:  # pydantic's ValidationError is a ValueError
            raise VectorIndexError(f"the vector index returned a malformed row: {type(exc).__name__}") from exc
        cases.sort(key=lambda case: (-case.similarity, case.case_id))  # ties: deterministic order
        return cases

    def count(self, stress_test_id: str) -> int:
        where = f"stress_test_id = '{_checked(stress_test_id)}'"
        return self._bounded(lambda: self._table().count_rows(where), "vector index count")
