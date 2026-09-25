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
            )
            self._items[comment.comment_id] = item
            return item, True

    def get_by_comment_id(self, comment_id: int) -> Optional[ReviewItem]:
        with self._lock:
            return self._items.get(comment_id)

    def list_items(self) -> List[ReviewItem]:
        with self._lock:
            return sorted(self._items.values(), key=lambda item: item.comment_id)
