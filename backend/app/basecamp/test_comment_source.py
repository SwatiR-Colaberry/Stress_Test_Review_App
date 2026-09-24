import json
import logging

import pytest

from app.basecamp.comment_source import (
    CommentSource,
    CommentSourceUnavailable,
    FixtureCommentSource,
    fetch_with_retry,
)


class _FlakySource(CommentSource):
    """Raises the given errors in order, then returns rows."""

    def __init__(self, errors, rows=()):
        self.errors = list(errors)
        self.rows = list(rows)
        self.calls = 0
        self.timeouts = []

    def fetch_comments(self, timeout_s):
        self.calls += 1
        self.timeouts.append(timeout_s)
        if self.errors:
            raise self.errors.pop(0)
        return list(self.rows)


def _no_sleep(_seconds):
    pass


def test_fixture_source_returns_its_rows():
    rows = [{"comment_id": 1}]
    assert fetch_with_retry(FixtureCommentSource(rows), sleep=_no_sleep) == rows


def test_recovers_after_a_transient_failure_and_passes_the_timeout():
    source = _FlakySource([ConnectionError("down")], rows=[{"comment_id": 1}])
    assert fetch_with_retry(source, timeout_s=7.5, sleep=_no_sleep) == [{"comment_id": 1}]
    assert source.calls == 2
    assert source.timeouts == [7.5, 7.5]


def test_gives_up_after_exactly_max_attempts_with_a_visible_error(caplog):
    caplog.set_level(logging.INFO, logger="stress_test_review.comment_source")
    source = _FlakySource([TimeoutError(), TimeoutError(), TimeoutError(), TimeoutError()])
    sleeps = []
    with pytest.raises(CommentSourceUnavailable, match="after 3 attempts"):
        fetch_with_retry(source, max_attempts=3, sleep=sleeps.append)
    assert source.calls == 3
    assert sleeps == [0.5, 1.0]  # no sleep after the final attempt
    events = [json.loads(r.getMessage()) for r in caplog.records]
    assert [e["attempt"] for e in events] == [1, 2, 3]
    assert all(e["error_class"] == "TimeoutError" for e in events)


def test_an_empty_backoff_schedule_is_rejected_up_front():
    source = _FlakySource([])
    with pytest.raises(ValueError, match="backoff_s"):
        fetch_with_retry(source, backoff_s=(), sleep=_no_sleep)
    assert source.calls == 0


def test_an_unexpected_error_is_not_retried():
    source = _FlakySource([KeyError("bad column")])
    with pytest.raises(KeyError):
        fetch_with_retry(source, sleep=_no_sleep)
    assert source.calls == 1
