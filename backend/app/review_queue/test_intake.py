import json
import logging
from datetime import datetime, timezone

import pytest

from app.audit.trail import AuditWriteError, InMemoryAuditTrail
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


@pytest.fixture
def audit():
    return InMemoryAuditTrail()


@pytest.fixture(autouse=True)
def _capture_info(caplog):
    caplog.set_level(logging.INFO, logger="stress_test_review.intake")


# Acceptance 1: '##Critique##' -> a Pending review item is created.
def test_critique_marker_creates_a_pending_review_item(store, audit):
    result = process_comment(_row("V2 ready. ##Critique##"), store, audit)
    assert result.outcome == "review_created"
    item = store.get_by_comment_id(1001)
    assert item is not None and item.status == "Pending"
    assert item.message_id == 500
    assert result.review_id == item.review_id


# Acceptance 2: '## Review ##' -> no review item.
def test_review_marker_creates_no_item(store, audit):
    result = process_comment(_row("## Review ##"), store, audit)
    assert result.outcome == "no_marker"
    assert store.list_items() == []


# Acceptance 3: the detection event is logged with the exact comment ID.
def test_detection_event_is_logged_with_the_exact_comment_id(store, audit, caplog):
    result = process_comment(_row("##Critique##", comment_id=987654321), store, audit, correlation_id="corr-1")
    detected = [line for line in _log_lines(caplog) if line["event"] == "critique_marker_detected"]
    assert len(detected) == 1
    assert detected[0]["comment_id"] == 987654321
    assert detected[0]["review_id"] == result.review_id
    assert detected[0]["correlation_id"] == "corr-1"


def test_a_comment_without_a_marker_is_logged_with_its_comment_id(store, audit, caplog):
    process_comment(_row("Can you give this a quick critique?", comment_id=42), store, audit)
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
def test_malformed_comment_data_creates_no_item_and_is_logged(store, audit, caplog, raw):
    result = process_comment(raw, store, audit)
    assert result.outcome == "malformed"
    assert store.list_items() == []
    [line] = _log_lines(caplog)
    assert line["event"] == "comment_rejected_malformed"
    assert line["error_class"] == "ValidationError"


def test_a_malformed_row_still_logs_its_comment_id_when_readable(store, audit, caplog):
    process_comment({"comment_id": 1001, "message_id": 500, "created_at": _NOW}, store, audit)
    [line] = _log_lines(caplog)
    assert line["comment_id"] == 1001
    assert line["invalid_fields"] == ["body"]


def test_processing_the_same_comment_twice_creates_only_one_item(store, audit):
    first = process_comment(_row("##Critique##"), store, audit)
    second = process_comment(_row("##Critique##"), store, audit)
    assert (first.outcome, second.outcome) == ("review_created", "already_queued")
    assert first.review_id == second.review_id
    assert len(store.list_items()) == 1


# --- STORY-011: every intake action is recorded in the audit trail ---

class _BrokenAuditTrail(InMemoryAuditTrail):
    def record(self, event):
        raise AuditWriteError("disk full")


@pytest.mark.parametrize(
    "raw, action, outcome",
    [
        (_row("##Critique##"), "review_created", "success"),
        (_row("## Review ##"), "comment_no_marker", "success"),
        ({"comment_id": 1001, "message_id": 500, "created_at": _NOW}, "comment_rejected_malformed", "failure"),
    ],
)
def test_each_intake_outcome_is_recorded_once_in_the_audit_trail(store, audit, raw, action, outcome):
    result = process_comment(raw, store, audit, correlation_id="corr-9")
    [event] = audit.read_all()
    assert (event.action, event.outcome, event.actor_id) == (action, outcome, "system")
    assert (event.comment_id, event.review_id, event.correlation_id) == (1001, result.review_id, "corr-9")


def test_a_repeat_comment_is_audited_as_already_queued(store, audit):
    process_comment(_row("##Critique##"), store, audit)
    process_comment(_row("##Critique##"), store, audit)
    assert [e.action for e in audit.read_all()] == ["review_created", "review_already_queued"]


def test_the_audit_record_never_contains_the_comment_text(store, audit):
    process_comment(_row("secret-looking body ##Critique##"), store, audit)
    assert "secret-looking" not in audit.read_all()[0].model_dump_json()


def test_when_the_audit_write_fails_no_result_is_returned_and_the_failure_is_logged(store, caplog):
    with pytest.raises(AuditWriteError):
        process_comment(_row("##Critique##"), store, _BrokenAuditTrail())
    failures = [line for line in _log_lines(caplog) if line["event"] == "audit_write_failed"]
    assert len(failures) == 1
    assert (failures[0]["error_class"], failures[0]["audit_action"]) == ("AuditWriteError", "review_created")


def test_rerunning_after_an_audit_failure_records_the_item_without_duplicating_it(store, audit):
    with pytest.raises(AuditWriteError):
        process_comment(_row("##Critique##"), store, _BrokenAuditTrail())
    retry = process_comment(_row("##Critique##"), store, audit)
    assert retry.outcome == "already_queued"
    assert len(store.list_items()) == 1
    assert [e.action for e in audit.read_all()] == ["review_already_queued"]


# --- ##Please Critique##: counted, with a reminder for the student ---

def test_please_critique_creates_a_review_with_a_reminder_note(store, audit):
    result = process_comment(_row("##Please Critique## my Dataset and Data Science Problem"), store, audit)
    assert result.outcome == "review_created"
    item = store.get_by_comment_id(1001)
    assert item.status == "Pending"
    assert "just write ##Critique##" in item.marker_note
    assert result.marker_note == item.marker_note
    [event] = audit.read_all()
    assert (event.action, event.reason_code) == ("review_created", "NONSTANDARD_MARKER")


def test_the_standard_marker_has_no_reminder_note(store, audit):
    result = process_comment(_row("##Critique##"), store, audit)
    assert store.get_by_comment_id(1001).marker_note is None and result.marker_note is None
    assert audit.read_all()[0].reason_code is None


def test_please_critique_twice_creates_one_item_and_keeps_the_note(store, audit):
    first = process_comment(_row("##Please Critique##"), store, audit)
    second = process_comment(_row("##Please Critique##"), store, audit)
    assert (first.outcome, second.outcome) == ("review_created", "already_queued")
    assert len(store.list_items()) == 1 and second.marker_note == first.marker_note
    assert [e.reason_code for e in audit.read_all()] == ["NONSTANDARD_MARKER", "NONSTANDARD_MARKER"]


@pytest.mark.parametrize("body", ["#Critique#", "please critique my work"])
def test_other_near_misses_still_create_nothing(store, audit, body):
    assert process_comment(_row(body), store, audit).outcome == "no_marker"
    assert store.list_items() == []
