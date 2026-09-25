from datetime import datetime, timezone

import pytest

from app.basecamp.comment_source import CommentSource, CommentSourceUnavailable, FixtureCommentSource
from app.review_queue import intake
from app.audit.trail import InMemoryAuditTrail
from app.review_queue.store import InMemoryReviewQueueStore

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
_ROWS = [
    {"comment_id": 1001, "message_id": 500, "body": "##Critique##", "created_at": _NOW},
    {"comment_id": 1002, "message_id": 500, "body": "## Review ##", "created_at": _NOW},
    {"comment_id": 1003, "message_id": 501, "body": "done ## critique ##", "created_at": _NOW},
]


class _DownSource(CommentSource):
    def fetch_comments(self, timeout_s):
        raise ConnectionError("SQL Server unreachable")


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    monkeypatch.setattr("app.basecamp.comment_source.time.sleep", lambda _s: None)


def test_run_intake_queues_only_the_critique_comments():
    store = InMemoryReviewQueueStore()
    results = intake.run_intake(FixtureCommentSource(_ROWS), store, InMemoryAuditTrail())
    assert [r.outcome for r in results] == ["review_created", "no_marker", "review_created"]
    assert [i.comment_id for i in store.list_items()] == [1001, 1003]


def test_running_intake_twice_gives_the_same_queue():
    store = InMemoryReviewQueueStore()
    first = intake.run_intake(FixtureCommentSource(_ROWS), store, InMemoryAuditTrail())
    second = intake.run_intake(FixtureCommentSource(_ROWS), store, InMemoryAuditTrail())
    assert [r.review_id for r in first] == [r.review_id for r in second]
    assert [r.outcome for r in second] == ["already_queued", "no_marker", "already_queued"]
    assert len(store.list_items()) == 2


def test_unreachable_source_raises_and_leaves_the_queue_untouched():
    store = InMemoryReviewQueueStore()
    with pytest.raises(CommentSourceUnavailable):
        intake.run_intake(_DownSource(), store, InMemoryAuditTrail())
    assert store.list_items() == []
