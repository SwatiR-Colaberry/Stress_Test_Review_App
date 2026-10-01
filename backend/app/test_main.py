import pytest
from fastapi.testclient import TestClient

from app.auth.fake import TestSignIn
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _signed_in():
    """STORY-014: every API except /health needs a Basecamp sign-in."""
    TestSignIn(app).sign_in(client, "jane.reviewer@example.com")
    yield
    client.cookies.clear()


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_finalize_check_happy_path():
    body = {
        "review_id": "rev-1",
        "final_feedback_text": "Looks good, ship it.",
        "ai_draft_author_id": "claude-ai",
        "reviewer_decision": {
            "reviewer_id": "jane.reviewer",
            "outcome": "approved",
            "decided_at": "2026-09-16T00:00:00Z",
        },
    }
    response = client.post("/reviews/finalize-check", json=body)
    assert response.status_code == 200
    assert response.json() == {"safe": True}


def test_finalize_check_rejects_ai_approver():
    body = {
        "review_id": "rev-2",
        "final_feedback_text": "x",
        "ai_draft_author_id": "claude-ai",
        "reviewer_decision": {"reviewer_id": "claude-ai", "outcome": "approved"},
    }
    response = client.post("/reviews/finalize-check", json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "AI_CANNOT_APPROVE"


def test_finalize_check_missing_decision_returns_409_not_500():
    body = {"review_id": "rev-3", "final_feedback_text": "x"}
    response = client.post("/reviews/finalize-check", json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "NO_HUMAN_REVIEW"


def test_finalize_check_malformed_request_returns_422_not_500():
    # Contract Enforcement Layer: malformed input rejected before reaching
    # business logic. Missing the required review_id field entirely.
    response = client.post("/reviews/finalize-check", json={"final_feedback_text": "x"})
    assert response.status_code == 422


def test_scan_credentials_flags_a_leak():
    response = client.post(
        "/security/scan-credentials",
        json={"content": 'aws_access_key_id = "AKIAIOSFODNN7EXAMPLE"'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["safe"] is False
    assert any(f["pattern"] == "AWS_ACCESS_KEY_ID" for f in body["findings"])


def test_scan_credentials_clean_content():
    response = client.post(
        "/security/scan-credentials",
        json={"content": "api_key = os.environ['ANTHROPIC_API_KEY']"},
    )
    assert response.json() == {"safe": True, "findings": []}


def test_detect_marker_triggers():
    response = client.post("/basecamp/critique-marker/detect", json={"comment_body": "Done, ##Critique##"})
    assert response.json() == {"is_critique_marker": True, "normalized_marker": "##Critique##"}


def test_detect_marker_rejects_near_miss():
    response = client.post("/basecamp/critique-marker/detect", json={"comment_body": "##Review##"})
    assert response.json() == {"is_critique_marker": False, "normalized_marker": None}


def test_reviewer_pages_and_their_shared_files_are_always_revalidated():
    # A cached old reviewer.css / review_logic.js broke the new queue page
    # (2026-09-30); no-cache makes the browser check before reusing a copy.
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    TestSignIn(app).sign_in(client)  # STORY-014: pages need a sign-in
    for path in ("/queue/", "/queue/queue.js", "/reviewer/reviewer.css", "/reviewer/review_logic.js",
                 "/rules/", "/rules/rules.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-cache", path
