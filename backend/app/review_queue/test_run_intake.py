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


# --- A critique request that already has a reviewer's answer later in the same thread ---

def _at(hour):
    return datetime(2026, 9, 24, hour, 0, tzinfo=timezone.utc)


def _thread(*rows):
    return [{"comment_id": c, "message_id": m, "body": b, "created_at": _at(h)} for c, m, h, b in rows]


@pytest.mark.parametrize("answer", ["Well done ##Approved##", "1. Add a link.\n##FeedbackGiven##"])
def test_a_critique_already_answered_later_in_the_thread_is_not_queued(answer):
    store, audit = InMemoryReviewQueueStore(), InMemoryAuditTrail()
    rows = _thread((2001, 600, 9, "Please ##Critique## my ST0"), (2002, 600, 10, answer))
    results = intake.run_intake(FixtureCommentSource(rows), store, audit)
    assert results[0].outcome == "no_marker" and results[0].review_id is None
    assert store.list_items() == []
    skipped = [e for e in audit.read_all() if e.comment_id == 2001]
    assert [(e.action, e.reason_code) for e in skipped] == [("comment_no_marker", "ALREADY_ANSWERED")]


def test_a_resubmission_after_the_answer_is_queued():
    store = InMemoryReviewQueueStore()
    rows = _thread((2001, 600, 9, "##Critique## v1"), (2002, 600, 10, "##FeedbackGiven##"),
                   (2003, 600, 11, "##Critique## v2, fixed"))
    results = intake.run_intake(FixtureCommentSource(rows), store, InMemoryAuditTrail())
    assert [r.outcome for r in results] == ["no_marker", "no_marker", "review_created"]
    assert [i.comment_id for i in store.list_items()] == [2003]


def test_an_answer_in_another_thread_or_earlier_does_not_count():
    store = InMemoryReviewQueueStore()
    rows = _thread((2010, 610, 8, "##Approved##"), (2011, 610, 9, "##Critique##"),
                   (2012, 611, 10, "##Critique##"), (2013, 612, 11, "##Approved##"))
    intake.run_intake(FixtureCommentSource(rows), store, InMemoryAuditTrail())
    assert [i.comment_id for i in store.list_items()] == [2011, 2012]


def test_an_answer_at_the_same_moment_does_not_count():
    store = InMemoryReviewQueueStore()
    rows = _thread((2020, 620, 9, "##Critique##"), (2021, 620, 9, "##Approved##"))
    intake.run_intake(FixtureCommentSource(rows), store, InMemoryAuditTrail())
    assert [i.comment_id for i in store.list_items()] == [2020]


def test_a_review_queued_before_the_answer_arrived_stays_queued_on_rerun():
    store = InMemoryReviewQueueStore()
    first = intake.run_intake(FixtureCommentSource(_thread((2030, 630, 9, "##Critique##"))), store,
                              InMemoryAuditTrail())
    rows = _thread((2030, 630, 9, "##Critique##"), (2031, 630, 10, "##FeedbackGiven##"))
    second = intake.run_intake(FixtureCommentSource(rows), store, InMemoryAuditTrail())
    assert second[0].outcome == "already_queued" and second[0].review_id == first[0].review_id


def test_a_malformed_row_in_the_thread_does_not_stop_the_answer_check():
    store = InMemoryReviewQueueStore()
    rows = _thread((2040, 640, 9, "##Critique##"), (2042, 640, 11, "##Approved##"))
    rows.insert(1, {"comment_id": "bad", "message_id": 640, "body": "x"})
    results = intake.run_intake(FixtureCommentSource(rows), store, InMemoryAuditTrail())
    assert [r.outcome for r in results] == ["no_marker", "malformed", "no_marker"]
    assert store.list_items() == []


def test_a_mix_of_timestamps_with_and_without_a_time_zone_does_not_crash_intake():
    store = InMemoryReviewQueueStore()
    rows = [{"comment_id": 2050, "message_id": 650, "body": "##Critique##", "created_at": "2026-09-24T09:00:00"},
            {"comment_id": 2051, "message_id": 650, "body": "##Approved##", "created_at": _at(10)}]
    intake.run_intake(FixtureCommentSource(rows), store, InMemoryAuditTrail())
    assert store.list_items() == []
