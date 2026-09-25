"""STORY-011: every finalize attempt is recorded in the audit trail, and an
attempt to auto-approve (no human decision, or an AI/system approver) is
blocked AND recorded."""
import pytest
from fastapi.testclient import TestClient

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditWriteError, InMemoryAuditTrail
from app.main import app

client = TestClient(app)

_HUMAN_APPROVED = {
    "review_id": "rev-1",
    "final_feedback_text": "Looks good.",
    "ai_draft_author_id": "claude-ai",
    "reviewer_decision": {"reviewer_id": "jane.reviewer", "outcome": "approved"},
}


class _BrokenAuditTrail(InMemoryAuditTrail):
    def record(self, event):
        raise AuditWriteError("disk full")


@pytest.fixture
def audit():
    trail = InMemoryAuditTrail()
    app.dependency_overrides[get_audit_trail] = lambda: trail
    return trail


def test_a_human_approval_is_allowed_and_recorded_under_the_reviewer(audit):
    response = client.post("/reviews/finalize-check", json=_HUMAN_APPROVED, headers={"X-Correlation-ID": "c-1"})
    assert response.status_code == 200
    [event] = audit.read_all()
    assert (event.action, event.outcome, event.actor_id) == ("finalize_allowed", "success", "jane.reviewer")
    assert (event.review_id, event.correlation_id, event.reason_code) == ("rev-1", "c-1", None)


@pytest.mark.parametrize(
    "decision, reason_code, actor_id",
    [
        (None, "NO_HUMAN_REVIEW", "unidentified"),  # auto-approve with no human review at all
        ({"reviewer_id": "system", "outcome": "approved"}, "AI_CANNOT_APPROVE", "system"),
        ({"reviewer_id": "claude-ai", "outcome": "approved"}, "AI_CANNOT_APPROVE", "claude-ai"),
        ({"reviewer_id": "jane.reviewer", "outcome": "pending"}, "NOT_APPROVED", "jane.reviewer"),
    ],
)
def test_an_auto_approve_attempt_is_blocked_and_recorded(audit, decision, reason_code, actor_id):
    body = {**_HUMAN_APPROVED, "reviewer_decision": decision}
    response = client.post("/reviews/finalize-check", json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == reason_code
    [event] = audit.read_all()
    assert (event.action, event.outcome, event.reason_code, event.actor_id) == (
        "finalize_blocked", "blocked", reason_code, actor_id,
    )


def test_if_the_audit_trail_is_down_even_a_valid_approval_is_refused():
    app.dependency_overrides[get_audit_trail] = lambda: _BrokenAuditTrail()
    response = client.post("/reviews/finalize-check", json=_HUMAN_APPROVED)
    assert response.status_code == 503
    assert response.json()["detail"]["error_class"] == "AuditWriteError"


def test_malformed_request_is_rejected_before_any_audit_write(audit):
    assert client.post("/reviews/finalize-check", json={"final_feedback_text": "x"}).status_code == 422
    assert audit.read_all() == []


@pytest.mark.parametrize("field", ["review_id", "reviewer_id"])
def test_an_oversized_id_is_rejected_with_422_not_a_500(audit, field):
    body = {**_HUMAN_APPROVED, "reviewer_decision": dict(_HUMAN_APPROVED["reviewer_decision"])}
    if field == "review_id":
        body["review_id"] = "r" * 129
    else:
        body["reviewer_decision"]["reviewer_id"] = "x" * 129
    assert client.post("/reviews/finalize-check", json=body).status_code == 422
    assert audit.read_all() == []


def test_the_longest_accepted_id_is_recorded_in_full(audit):
    body = {**_HUMAN_APPROVED, "review_id": "r" * 128}
    assert client.post("/reviews/finalize-check", json=body).status_code == 200
    assert audit.read_all()[0].review_id == "r" * 128
