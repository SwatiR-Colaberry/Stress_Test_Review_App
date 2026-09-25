from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.audit.trail import (
    AuditReadError,
    AuditWriteError,
    InMemoryAuditTrail,
    JsonlFileAuditTrail,
)
from app.models import AuditEvent

_NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _event(event_id="evt-1", action="review_created", **overrides):
    fields = dict(
        event_id=event_id,
        recorded_at=_NOW,
        action=action,
        actor_id="system",
        outcome="success",
        correlation_id="corr-1",
        comment_id=1001,
        message_id=500,
        review_id="review-1",
    )
    fields.update(overrides)
    return AuditEvent(**fields)


@pytest.mark.parametrize("make_trail", [
    lambda tmp: InMemoryAuditTrail(),
    lambda tmp: JsonlFileAuditTrail(tmp / "audit" / "audit_trail.jsonl"),
])
def test_recorded_events_read_back_in_order(tmp_path, make_trail):
    trail = make_trail(tmp_path)
    trail.record(_event("evt-1"))
    trail.record(_event("evt-2", action="finalize_blocked", outcome="blocked", reason_code="AI_CANNOT_APPROVE"))
    events = trail.read_all()
    assert [e.event_id for e in events] == ["evt-1", "evt-2"]
    assert events[1].reason_code == "AI_CANNOT_APPROVE"


def test_file_trail_survives_a_restart_and_only_appends(tmp_path):
    path = tmp_path / "audit_trail.jsonl"
    JsonlFileAuditTrail(path).record(_event("evt-1"))
    JsonlFileAuditTrail(path).record(_event("evt-2"))  # a new instance, as after a restart
    assert [e.event_id for e in JsonlFileAuditTrail(path).read_all()] == ["evt-1", "evt-2"]
    assert len(path.read_text().splitlines()) == 2


def test_missing_file_reads_as_empty(tmp_path):
    assert JsonlFileAuditTrail(tmp_path / "none.jsonl").read_all() == []


def test_unwritable_location_raises_instead_of_losing_the_event(tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("a file where the folder should be")
    trail = JsonlFileAuditTrail(blocker / "audit_trail.jsonl")
    with pytest.raises(AuditWriteError) as excinfo:
        trail.record(_event())
    assert excinfo.value.error_class == "AuditWriteError"


def test_corrupt_line_is_reported_not_skipped(tmp_path):
    path = tmp_path / "audit_trail.jsonl"
    trail = JsonlFileAuditTrail(path)
    trail.record(_event())
    with open(path, "a") as handle:
        handle.write("{not json\n")
    with pytest.raises(AuditReadError, match="line 2"):
        trail.read_all()


def test_event_rejects_unknown_actions_and_free_text_fields():
    with pytest.raises(ValidationError):
        _event(action="approved_by_ai")
    with pytest.raises(ValidationError):
        _event(actor_id="")
    # No free-text field exists, so comment bodies cannot be smuggled in.
    assert "body" not in AuditEvent.model_fields
    assert "comment" not in AuditEvent.model_fields


def test_a_torn_last_line_does_not_swallow_the_next_event(tmp_path):
    path = tmp_path / "audit_trail.jsonl"
    trail = JsonlFileAuditTrail(path)
    trail.record(_event("evt-1"))
    with open(path, "a") as handle:
        handle.write('{"event_id": "evt-torn", "recor')  # crash mid-write: no newline
    trail.record(_event("evt-2"))
    lines = path.read_text().splitlines()
    assert len(lines) == 3
    assert AuditEvent.model_validate_json(lines[2]).event_id == "evt-2"
    with pytest.raises(AuditReadError, match="line 2"):  # the torn line is still reported
        trail.read_all()


def test_concurrent_writers_lose_no_events(tmp_path):
    import threading

    trail = JsonlFileAuditTrail(tmp_path / "audit_trail.jsonl")
    threads = [
        threading.Thread(target=lambda n=n: [trail.record(_event(f"evt-{n}-{i}")) for i in range(25)])
        for n in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    ids = [e.event_id for e in trail.read_all()]
    assert len(ids) == 200 and len(set(ids)) == 200


def test_event_rejects_oversized_ids():
    with pytest.raises(ValidationError):
        _event(actor_id="x" * 129)
    with pytest.raises(ValidationError):
        _event(review_id="r" * 129)
