"""Review Queue storage (REQ-002).

One review item per Basecamp comment version: the store is keyed on
comment_id, so re-processing the same comment returns the existing item
instead of creating a duplicate (Master Spec §26 "Duplicate critique event").
A later comment on the same thread has a new comment_id and therefore gets
its own review, leaving the earlier one intact (Master Spec §4).

Only an in-memory implementation exists today (decision logged in PROGRESS.md,
session CC-20260924-e18o): items are lost on restart. A database-backed store
implements the same interface once a database is chosen.
"""
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from app.models import BasecampComment, ReviewItem


class ReviewQueueStore(ABC):
    @abstractmethod
    def create_pending(
        self, comment: BasecampComment, marker_note: Optional[str] = None
    ) -> Tuple[ReviewItem, bool]:
        """Returns (item, created). created is False when an item for this
        comment_id already existed; the existing item is returned unchanged."""

    @abstractmethod
    def get_by_comment_id(self, comment_id: int) -> Optional[ReviewItem]:
        ...

    @abstractmethod
    def list_items(self) -> List[ReviewItem]:
        ...

    @abstractmethod
    def get_by_review_id(self, review_id: str) -> Optional[ReviewItem]:
        ...

    @abstractmethod
    def mark_completed(self, review_id: str) -> Optional[ReviewItem]:
        """Sets status Completed (REQ-007). Only the STORY-006 posting service
        calls it, after Basecamp confirmed the feedback comment. Idempotent:
        an already Completed item is returned unchanged. None if no such review."""


class InMemoryReviewQueueStore(ReviewQueueStore):
    def __init__(
        self,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._items: Dict[int, ReviewItem] = {}
        self._lock = threading.Lock()
        self._clock = clock
        self._new_id = new_id

    def create_pending(
        self, comment: BasecampComment, marker_note: Optional[str] = None
    ) -> Tuple[ReviewItem, bool]:
        # Check and insert under one lock so two concurrent calls for the
        # same comment cannot both create an item.
        with self._lock:
            existing = self._items.get(comment.comment_id)
            if existing is not None:
                return existing, False
            item = ReviewItem(
                review_id=self._new_id(),
                comment_id=comment.comment_id,
                message_id=comment.message_id,
                status="Pending",
                created_at=self._clock(),
                marker_note=marker_note,
                author_name=comment.author_name,
                app_url=comment.app_url,
                project_id=comment.project_id,
            )
            self._items[comment.comment_id] = item
            return item, True

    def get_by_comment_id(self, comment_id: int) -> Optional[ReviewItem]:
        with self._lock:
            return self._items.get(comment_id)

    def list_items(self) -> List[ReviewItem]:
        with self._lock:
            return sorted(self._items.values(), key=lambda item: item.comment_id)

    def get_by_review_id(self, review_id: str) -> Optional[ReviewItem]:
        with self._lock:
            return self._find(review_id)

    def mark_completed(self, review_id: str) -> Optional[ReviewItem]:
        with self._lock:
            item = self._find(review_id)
            if item is None or item.status == "Completed":
                return item
            completed = item.model_copy(update={"status": "Completed"})
            self._items[item.comment_id] = completed
            return completed

    def _find(self, review_id: str) -> Optional[ReviewItem]:
        return next((i for i in self._items.values() if i.review_id == review_id), None)
