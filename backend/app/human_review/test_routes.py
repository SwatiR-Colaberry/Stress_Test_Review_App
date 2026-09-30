"""End-to-end reviewer flow through the FastAPI app (STORY-005 acceptance)."""
import logging
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditWriteError, InMemoryAuditTrail
from app.evaluation.store import ResultStore
from app.human_review.dependencies import get_draft_source, get_review_action_store
from app.human_review.drafts import DraftSource
from app.human_review.store import ReviewActionStore
from app.human_review.test_store import DRAFT
from app.main import app
from app.models import BasecampComment, EvaluationResult, PrecheckResults, TokenUsage
from app.review_queue.store import InMemoryReviewQueueStore

_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
REVIEWER = {"X-Reviewer-Id": "reviewer-7"}
BASECAMP_URL = "https://3.basecamp.com/999/buckets/1/messages/500#__recording_2002"


def _evaluation(rule_version="v1", findings=DRAFT):
    return EvaluationResult(
        comment_id=2002, message_id=500, stress_test_id="ST0", rule_version=rule_version,
        model="claude-sonnet-5", evaluated_at=_NOW, correlation_id="c-1", stages_evaluated=[1],
        passed_rule_ids=[], findings=list(findings),
        prechecks=PrecheckResults(problem_count=None, selected_count=0, link_count=0,
                                  dataset_link_present=False, dataset_file_count=0, image_count=0),
        usage=TokenUsage(input_tokens=10),
    )


class _FailingAudit(InMemoryAuditTrail):
    fail = True

    def record(self, event):
        if self.fail:
            raise AuditWriteError("disk full")
        super().record(event)


@pytest.fixture
def audit():
    return InMemoryAuditTrail()


@pytest.fixture
def client(tmp_path, audit):
    queue = InMemoryReviewQueueStore(new_id=lambda: "r-1")
    queue.create_pending(BasecampComment(comment_id=2002, message_id=500, body="##Critique##", created_at=_NOW,
                                         author_name="Asha Verma", app_url=BASECAMP_URL))
    ResultStore(tmp_path / "evaluations").put(_evaluation())
    store = ReviewActionStore(tmp_path / "reviews")
    app.dependency_overrides[get_draft_source] = lambda: DraftSource(queue, tmp_path / "evaluations")
    app.dependency_overrides[get_review_action_store] = lambda: store
    app.dependency_overrides[get_audit_trail] = lambda: audit
    yield TestClient(app)
    app.dependency_overrides.clear()


def _post(client, action_id, kind, headers=REVIEWER, **fields):
    return client.post("/reviews/r-1/actions", headers=headers, json={"action_id": action_id, "kind": kind, **fields})


def test_a_reviewer_sees_the_ai_findings_pending(client):
    view = client.get("/reviews/r-1/findings", headers=REVIEWER).json()
    assert [(f["finding_id"], f["decision"]) for f in view["findings"]] == [("ST0-001", "pending"), ("ST0-002", "pending")]
    assert view["prepared"] is None and view["rule_version"] == "v1"


def test_approving_the_findings_prepares_feedback_for_posting(client):
    _post(client, "a1", "approve_finding", finding_id="ST0-001")
    _post(client, "a2", "approve_finding", finding_id="ST0-002")
    response = client.post("/reviews/r-1/prepare", headers=REVIEWER)
    assert response.status_code == 200
    assert response.json()["status"] == "ready_to_post"
    assert response.json()["feedback_text"] == "1. AI suggestion.\n\n2. AI suggestion."
    assert client.get("/reviews/r-1/findings", headers=REVIEWER).json()["prepared"]["reviewer_id"] == "reviewer-7"


def test_edits_are_saved_and_prepared_for_posting(client):
    saved = _post(client, "a1", "edit_finding", finding_id="ST0-001", text="Please link the Kaggle dataset.")
    assert saved.status_code == 200
    reread = client.get("/reviews/r-1/findings", headers=REVIEWER).json()["findings"][0]
    assert reread["feedback_text"] == "Please link the Kaggle dataset." and reread["edited"] is True
    assert reread["ai_draft"]["suggested_feedback"] == "AI suggestion."  # the AI draft is kept
    _post(client, "a2", "reject_finding", finding_id="ST0-002")
    _post(client, "a3", "add_finding", text="Nice problem statement.")
    prepared = client.post("/reviews/r-1/prepare", headers=REVIEWER).json()
    assert prepared["feedback_text"] == "1. Please link the Kaggle dataset.\n\n2. Nice problem statement."


def test_every_reviewer_action_is_audited_with_reviewer_and_time(client, audit):
    _post(client, "a1", "edit_finding", finding_id="ST0-001", text="Reviewer words.")
    _post(client, "a2", "reject_finding", finding_id="ST0-002")
    _post(client, "a3", "add_finding", text="Extra point.", rule_id="ST0-003")
    client.post("/reviews/r-1/prepare", headers=REVIEWER)
    _post(client, "a4", "approve_finding", finding_id="ST0-001")  # locked: blocked, still audited
    events = audit.read_all()
    assert [(e.action, e.outcome, e.rule_id) for e in events] == [
        ("reviewer_finding_edited", "success", "ST0-001"),
        ("reviewer_finding_rejected", "success", "ST0-002"),
        ("reviewer_finding_added", "success", "ST0-003"),
        ("reviewer_feedback_prepared", "success", None),
        ("reviewer_action_blocked", "blocked", None),
    ]
    assert events[-1].reason_code == "REVIEW_LOCKED"
    assert all(e.actor_id == "reviewer-7" and e.review_id == "r-1" and e.comment_id == 2002 for e in events)
    assert all(e.recorded_at.tzinfo is not None for e in events)
    assert [e.recorded_at for e in events] == sorted(e.recorded_at for e in events)


def test_a_retried_action_is_saved_and_audited_once(client, audit):
    first = _post(client, "a1", "add_finding", text="Once.")
    second = _post(client, "a1", "add_finding", text="Once.")
    assert first.json() == second.json()
    assert len(second.json()["findings"]) == 3
    assert [e.action for e in audit.read_all()] == ["reviewer_finding_added"]


def test_when_the_audit_trail_fails_the_action_is_not_reported_and_a_retry_completes_it(client):
    failing = _FailingAudit()
    app.dependency_overrides[get_audit_trail] = lambda: failing
    response = _post(client, "a1", "approve_finding", finding_id="ST0-001")
    assert response.status_code == 503
    assert "retry" in response.json()["detail"]["message"].lower()
    failing.fail = False
    assert _post(client, "a1", "approve_finding", finding_id="ST0-001").status_code == 200
    assert [e.action for e in failing.read_all()] == ["reviewer_finding_approved"]


def test_when_storage_fails_the_edit_is_reported_not_saved(client, tmp_path):
    app.dependency_overrides[get_review_action_store] = lambda: ReviewActionStore(tmp_path / "broken")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "actions.jsonl").mkdir()
    response = _post(client, "a1", "edit_finding", finding_id="ST0-001", text="Lost?")
    assert response.status_code == 503
    assert response.json()["detail"]["error_class"] == "ReviewStoreError"


@pytest.mark.parametrize("headers, status, reason", [
    ({}, 401, "MISSING_REVIEWER_IDENTITY"),
    ({"X-Reviewer-Id": "claude"}, 403, "AI_CANNOT_REVIEW"),
])
def test_no_reviewer_or_an_ai_reviewer_is_refused_and_audited(client, audit, headers, status, reason):
    response = _post(client, "a1", "approve_finding", headers=headers, finding_id="ST0-001")
    assert response.status_code == status
    assert response.json()["detail"]["reason_code"] == reason
    assert [(e.action, e.reason_code) for e in audit.read_all()] == [("reviewer_action_blocked", reason)]


def test_ai_cannot_prepare_feedback(client):
    _post(client, "a1", "approve_finding", finding_id="ST0-001")
    _post(client, "a2", "approve_finding", finding_id="ST0-002")
    response = client.post("/reviews/r-1/prepare", headers={"X-Reviewer-Id": "claude"})
    assert response.status_code == 403
    assert client.get("/reviews/r-1/findings", headers=REVIEWER).json()["prepared"] is None


def test_preparing_with_undecided_findings_is_refused(client):
    _post(client, "a1", "approve_finding", finding_id="ST0-001")
    response = client.post("/reviews/r-1/prepare", headers=REVIEWER)
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "UNDECIDED_FINDINGS"


def test_an_unknown_review_is_404(client):
    response = client.get("/reviews/nope/findings", headers=REVIEWER)
    assert response.status_code == 404
    assert response.json()["detail"]["reason_code"] == "REVIEW_NOT_FOUND"


def test_a_review_without_an_ai_evaluation_is_404(client, tmp_path):
    queue = InMemoryReviewQueueStore(new_id=lambda: "r-2")
    queue.create_pending(BasecampComment(comment_id=3003, message_id=501, body="##Critique##", created_at=_NOW))
    app.dependency_overrides[get_draft_source] = lambda: DraftSource(queue, tmp_path / "evaluations")
    assert client.get("/reviews/r-2/findings", headers=REVIEWER).json()["detail"]["reason_code"] == "NO_AI_DRAFT"


def test_a_malformed_action_is_rejected_before_it_reaches_the_store(client, audit):
    response = _post(client, "a1", "edit_finding", finding_id="ST0-001")  # edit without text
    assert response.status_code == 422
    assert audit.read_all() == []


def test_the_newest_rule_version_is_the_draft(client, tmp_path):
    ResultStore(tmp_path / "evaluations").put(_evaluation(rule_version="v2", findings=DRAFT[:1]))
    assert client.get("/reviews/r-1/findings", headers=REVIEWER).json()["rule_version"] == "v2"


def test_the_reviewer_page_and_its_script_are_served(client):
    page = client.get("/reviewer/")
    assert page.status_code == 200 and "reviewer.js" in page.text
    script = client.get("/reviewer/reviewer.js")
    assert script.status_code == 200 and "X-Reviewer-Id" in script.text


def test_the_reviewer_sees_the_students_name_and_basecamp_link(client, audit):
    view = client.get("/reviews/r-1/findings", headers=REVIEWER).json()
    assert (view["student_name"], view["basecamp_url"]) == ("Asha Verma", BASECAMP_URL)
    _post(client, "a1", "approve_finding", finding_id="ST0-001")
    assert all("Asha Verma" not in e.model_dump_json() for e in audit.read_all())  # never in the audit trail


def test_a_review_without_a_name_or_link_still_opens(client, tmp_path):
    queue = InMemoryReviewQueueStore(new_id=lambda: "r-3")
    queue.create_pending(BasecampComment(comment_id=2002, message_id=500, body="##Critique##", created_at=_NOW))
    app.dependency_overrides[get_draft_source] = lambda: DraftSource(queue, tmp_path / "evaluations")
    view = client.get("/reviews/r-3/findings", headers=REVIEWER).json()
    assert (view["student_name"], view["basecamp_url"]) == (None, None)


def test_the_view_names_each_rule_in_plain_words(client):
    names = client.get("/reviews/r-1/findings", headers=REVIEWER).json()["rule_names"]
    assert names["ST0-001"] == "Dataset description is present"


def test_an_unknown_review_is_logged_not_silent(client, caplog):
    caplog.set_level(logging.WARNING, logger="stress_test_review.human_review")
    client.get("/reviews/nope/findings", headers=REVIEWER)
    assert '"event": "review_not_found"' in caplog.text and "REVIEW_NOT_FOUND" in caplog.text
