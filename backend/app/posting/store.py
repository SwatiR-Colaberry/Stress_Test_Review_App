"""Posting history (STORY-006): data/reviews/posted.jsonl, append-only and
git-ignored. SQL Server is not used (read-only, user rule 2026-09-25).

A review is posted once any record says "posted"; otherwise the latest record
is its posting state. A "posted" record is written only after Basecamp confirmed the comment, and is what allows the
review to be marked Completed (REQ-007).

Failures: cannot write/read -> PostingStoreError; a corrupt line ->
PostingStoreError naming the line, never skipped.
"""
import threading
from pathlib import Path
from typing import List, Optional

from app.evaluation.store import EvaluationStoreError, append_line, read_lines
from app.posting.models import PostingRecord

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "reviews"


class PostingStoreError(Exception):
    error_class = "PostingStoreError"


class PostingStore:
    def __init__(self, directory: Path = DEFAULT_DIR) -> None:
        self._path = Path(directory) / "posted.jsonl"
        self._lock = threading.Lock()

    def append(self, record: PostingRecord) -> None:
        with self._lock:
            try:
                append_line(self._path, record.model_dump_json())
            except EvaluationStoreError as exc:
                raise PostingStoreError(str(exc)) from exc

    def history(self, review_id: str) -> List[PostingRecord]:
        with self._lock:
            try:
                records = read_lines(self._path, PostingRecord)
            except EvaluationStoreError as exc:
                raise PostingStoreError(str(exc)) from exc
        return [r for r in records if r.review_id == review_id]

    def latest(self, review_id: str) -> Optional[PostingRecord]:
        records = self.history(review_id)
        return records[-1] if records else None

    def posted(self, review_id: str) -> Optional[PostingRecord]:
        """The first "posted" record, if any. Posted is final: a later record
        (e.g. a refusal written by a concurrent request) never undoes it."""
        return next((r for r in self.history(review_id) if r.status == "posted"), None)
