"""Review Queue UI routes end to end through the FastAPI app (STORY-012)."""
import pytest
from fastapi.testclient import TestClient

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditWriteError, InMemoryAuditTrail
from app.auth.fake import signed_in_client
from app.human_review.dependencies import get_draft_source, get_review_action_store
from app.human_review.test_routes import BASECAMP_URL
from app.human_review.test_store import DRAFT
from app.main import app
from app.posting.dependencies import get_posting_store
from app.queue_ui.test_service import _Env
from app.review_queue.dependencies import get_review_queue_store

REVIEWER = "reviewer-7@example.com"  # signed in with Basecamp (STORY-014)


class _FailingAudit(InMemoryAuditTrail):
    def record(self, event):
        raise AuditWriteError("disk full")


@pytest.fixture
def env(tmp_path):
    return _Env(tmp_path)


@pytest.fixture
def audit():
    return InMemoryAuditTrail()


@pytest.fixture
def client(env, audit):
    app.dependency_overrides[get_review_queue_store] = lambda: env.queue
    app.dependency_overrides[get_draft_source] = lambda: env.drafts
    app.dependency_overrides[get_review_action_store] = lambda: env.actions
    app.dependency_overrides[get_posting_store] = lambda: env.postings
    app.dependency_overrides[get_audit_trail] = lambda: audit
    yield signed_in_client(app, REVIEWER)
    app.dependency_overrides.clear()


# --- Acceptance ----------------------------------------------------------------

def test_a_pending_review_in_the_queue_shows_all_details_needed_for_review(client):
    rows = client.get("/queue-ui/reviews").json()
    assert [(r["review_id"], r["status"], r["student_name"]) for r in rows] == [("r-1", "Pending", "Asha Verma")]
    detail = client.get("/queue-ui/reviews/r-1").json()
    assert detail["status"] == "Pending"
    assert detail["basecamp_url"] == BASECAMP_URL and detail["stress_test_id"] == "ST0"
    assert [f["finding_id"] for f in detail["findings"]] == ["ST0-001", "ST0-002"]
    assert detail["findings"][0]["ai_draft"]["evidence"] == "e"


def test_a_completed_review_shows_status_and_history(client, env):
    env.act("a1", "approve_finding", finding_id="ST0-001")
    env.act("a2", "reject_finding", finding_id="ST0-002")
    env.actions.prepare("r-1", REVIEWER, DRAFT)
    env.post("posted")
    assert client.get("/queue-ui/reviews").json()[0]["status"] == "Completed"
    detail = client.get("/queue-ui/reviews/r-1").json()
    assert detail["status"] == "Completed"
    assert [h["kind"] for h in detail["history"]] == [
        "request_received", "ai_draft", "reviewer_action", "reviewer_action", "feedback_prepared", "posting"]
    assert detail["postings"][0]["status"] == "posted"


def test_every_ui_view_is_audited_with_timestamp_and_user_id(client, audit):
    client.get("/queue-ui/reviews")
    client.get("/queue-ui/reviews/r-1", headers={"X-Correlation-ID": "corr-1"})
    events = audit.read_all()
    assert [(e.action, e.actor_id, e.outcome, e.review_id) for e in events] == [
        ("queue_viewed", REVIEWER, "success", None),
        ("review_detail_viewed", REVIEWER, "success", "r-1")]
    assert all(e.recorded_at.tzinfo is not None for e in events)
    assert events[1].correlation_id == "corr-1"


def test_opening_a_review_twice_is_two_interactions_and_changes_nothing_else(client, audit, env):
    first = client.get("/queue-ui/reviews/r-1").json()
    assert client.get("/queue-ui/reviews/r-1").json() == first
    assert len({e.event_id for e in audit.read_all()}) == 2
    assert env.actions.history("r-1") == []


# --- Failure paths -------------------------------------------------------------

@pytest.mark.parametrize("path", ["/queue-ui/reviews", "/queue-ui/reviews/r-1"])
def test_without_signing_in_nothing_is_shown(client, audit, path, caplog):
    # STORY-014: refused before the route runs (logged, not a view, so no
    # view audit event); a claimed X-Reviewer-Id no longer gets anyone in.
    response = TestClient(app).get(path, headers={"X-Reviewer-Id": "reviewer-7"})
    assert response.status_code == 401
    assert response.json()["detail"]["reason_code"] == "NOT_SIGNED_IN"
    assert "Asha" not in response.text and audit.read_all() == []
    assert "NOT_SIGNED_IN" in caplog.text


def test_details_that_cannot_load_are_a_clear_error_and_audited(client, audit, env):
    assert client.get("/queue-ui/reviews/r-404").status_code == 404
    (env.dir / "reviews").mkdir(exist_ok=True)
    (env.dir / "reviews" / "actions.jsonl").write_text("{not json\n", encoding="utf-8")
    response = client.get("/queue-ui/reviews/r-1")
    assert response.status_code == 503
    assert response.json()["detail"]["reason_code"] == "REVIEWER_ACTIONS_UNREADABLE"
    assert [(e.outcome, e.reason_code) for e in audit.read_all()] == [
        ("failure", "REVIEW_NOT_FOUND"), ("failure", "REVIEWER_ACTIONS_UNREADABLE")]


def test_nothing_is_shown_when_the_view_cannot_be_audited(client, caplog):
    app.dependency_overrides[get_audit_trail] = lambda: _FailingAudit()
    response = client.get("/queue-ui/reviews/r-1")
    assert response.status_code == 503
    assert "findings" not in response.text
    assert '"audit_written": false' in caplog.text


def test_an_audit_failure_does_not_hide_the_original_error(client):
    app.dependency_overrides[get_audit_trail] = lambda: _FailingAudit()
    assert client.get("/queue-ui/reviews/r-404").status_code == 404


# --- The STORY-005 reviewer page's load is a UI interaction too ---------------

def test_opening_the_reviewer_page_is_audited_with_user_and_time(client, audit):
    assert client.get("/reviews/r-1/findings").status_code == 200
    assert TestClient(app).get("/reviews/r-1/findings").status_code == 401  # not signed in: not a view
    assert client.get("/reviews/r-404/findings").status_code == 404
    assert [(e.action, e.actor_id, e.outcome, e.review_id, e.reason_code) for e in audit.read_all()] == [
        ("review_detail_viewed", REVIEWER, "success", "r-1", None),
        ("review_detail_viewed", REVIEWER, "failure", "r-404", "REVIEW_NOT_FOUND")]
    assert all(e.recorded_at.tzinfo is not None for e in audit.read_all())


def test_a_review_that_cannot_be_rebuilt_is_a_409_and_is_audited(client, audit, env):
    from app.evaluation.store import ResultStore
    from app.human_review.test_routes import _evaluation
    env.act("a1", "approve_finding", finding_id="ST0-001")
    ResultStore(env.dir / "evaluations").put(_evaluation(rule_version="v2", findings=DRAFT[1:]))
    response = client.get("/queue-ui/reviews/r-1")
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "REVIEW_STATE_MISMATCH"
    assert [(e.outcome, e.reason_code) for e in audit.read_all()] == [("failure", "REVIEW_STATE_MISMATCH")]


def test_an_unexpected_error_is_still_audited_before_it_surfaces(audit):
    from app.queue_ui import viewing

    def broken():
        raise KeyError("surprise")
    with pytest.raises(KeyError):
        viewing.view_queue("reviewer-7", "corr-1", audit, broken)
    [event] = audit.read_all()
    assert (event.action, event.actor_id, event.outcome, event.reason_code) == (
        "queue_viewed", "reviewer-7", "failure", "KeyError")
