import json
import logging
from datetime import datetime, timezone

import pytest

from app.review_queue.intake import process_comment
from app.review_queue.store import InMemoryReviewQueueStore

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _row(body, comment_id=1001, message_id=500):
    return {"comment_id": comment_id, "message_id": message_id, "body": body, "created_at": _NOW}


def _log_lines(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "stress_test_review.intake"]


@pytest.fixture
def store():
    return InMemoryReviewQueueStore()


@pytest.fixture(autouse=True)
def _capture_info(caplog):
    caplog.set_level(logging.INFO, logger="stress_test_review.intake")


# Acceptance 1: '##Critique##' -> a Pending review item is created.
def test_critique_marker_creates_a_pending_review_item(store):
    result = process_comment(_row("V2 ready. ##Critique##"), store)
    assert result.outcome == "review_created"
    item = store.get_by_comment_id(1001)
    assert item is not None and item.status == "Pending"
    assert item.message_id == 500
    assert result.review_id == item.review_id


# Acceptance 2: '## Review ##' -> no review item.
def test_review_marker_creates_no_item(store):
    result = process_comment(_row("## Review ##"), store)
    assert result.outcome == "no_marker"
    assert store.list_items() == []


# Acceptance 3: the detection event is logged with the exact comment ID.
def test_detection_event_is_logged_with_the_exact_comment_id(store, caplog):
    result = process_comment(_row("##Critique##", comment_id=987654321), store, correlation_id="corr-1")
    detected = [line for line in _log_lines(caplog) if line["event"] == "critique_marker_detected"]
    assert len(detected) == 1
    assert detected[0]["comment_id"] == 987654321
    assert detected[0]["review_id"] == result.review_id
    assert detected[0]["correlation_id"] == "corr-1"


def test_a_comment_without_a_marker_is_logged_with_its_comment_id(store, caplog):
    process_comment(_row("Can you give this a quick critique?", comment_id=42), store)
    lines = _log_lines(caplog)
    assert [(line["event"], line["comment_id"]) for line in lines] == [("critique_marker_not_found", 42)]


@pytest.mark.parametrize(
    "raw",
    [
        {"comment_id": 1001, "message_id": 500, "created_at": _NOW},  # no body
        {"comment_id": "abc", "message_id": 500, "body": "##Critique##", "created_at": _NOW},
        {"comment_id": 1001, "body": "##Critique##", "created_at": _NOW},  # no message_id
        None,
        "##Critique##",
    ],
)
def test_malformed_comment_data_creates_no_item_and_is_logged(store, caplog, raw):
    result = process_comment(raw, store)
    assert result.outcome == "malformed"
    assert store.list_items() == []
    [line] = _log_lines(caplog)
    assert line["event"] == "comment_rejected_malformed"
    assert line["error_class"] == "ValidationError"


def test_a_malformed_row_still_logs_its_comment_id_when_readable(store, caplog):
    process_comment({"comment_id": 1001, "message_id": 500, "created_at": _NOW}, store)
    [line] = _log_lines(caplog)
    assert line["comment_id"] == 1001
    assert line["invalid_fields"] == ["body"]


def test_processing_the_same_comment_twice_creates_only_one_item(store):
    first = process_comment(_row("##Critique##"), store)
    second = process_comment(_row("##Critique##"), store)
    assert (first.outcome, second.outcome) == ("review_created", "already_queued")
    assert first.review_id == second.review_id
    assert len(store.list_items()) == 1
