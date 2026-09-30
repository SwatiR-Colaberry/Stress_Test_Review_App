"""POST /reviews/{id}/post through the FastAPI app (STORY-006), fake Basecamp."""
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditWriteError, InMemoryAuditTrail
from app.basecamp.config import BasecampConfigError
from app.human_review.dependencies import get_review_action_store
from app.main import app
from app.posting.config import PostingConfig
from app.posting.dependencies import get_basecamp_client_factory, get_posting_config, get_posting_store
from app.posting.store import PostingStore
from app.posting.fake import FakeThread
from app.posting.test_service import CONFIG, NOW, PROJECT, REVIEW, FakeReviews, prepared
from app.models import BasecampComment
from app.review_queue.dependencies import get_review_queue_store
from app.review_queue.store import InMemoryReviewQueueStore

REQUESTER = {"X-Reviewer-Id": "swati"}


class Env:
    def __init__(self, tmp_path):
        self.queue = InMemoryReviewQueueStore(new_id=lambda: REVIEW)
        self.queue.create_pending(BasecampComment(comment_id=9001, message_id=5001, body="##Critique##",
                                                  created_at=NOW, project_id=PROJECT))
        self.thread = FakeThread()
        self.audit = InMemoryAuditTrail()
        self.config = CONFIG
        self.client_factory = self.thread.client
        overrides = {
            get_review_queue_store: lambda: self.queue,
            get_review_action_store: lambda: FakeReviews(prepared()),
            get_posting_store: lambda: PostingStore(tmp_path),
            get_audit_trail: lambda: self.audit,
            get_basecamp_client_factory: lambda: self.client_factory,
            get_posting_config: lambda: self.config,
        }
        app.dependency_overrides.update(overrides)
        self.http = TestClient(app)

    def post(self, headers=REQUESTER, review=REVIEW):
        return self.http.post(f"/reviews/{review}/post", headers=headers)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("app.posting.service.time.sleep", lambda s: None)  # no real backoff waits
    yield Env(tmp_path)
    app.dependency_overrides.clear()


def test_post_route_posts_and_the_queue_shows_completed(env):
    response = env.post()
    assert response.status_code == 200
    assert response.json()["status"] == "posted" and response.json()["review_status"] == "Completed"
    assert env.http.get("/reviews/queue").json()[0]["status"] == "Completed"
    again = env.post()
    assert again.status_code == 200 and again.json()["already_posted"] is True
    assert len(env.thread.comments) == 1


def test_no_requester_is_401_logged_and_nothing_is_sent(env, caplog):
    caplog.set_level(logging.WARNING, logger="stress_test_review.posting")
    assert env.post(headers={}).status_code == 401
    assert env.thread.requests == []
    assert "MISSING_REVIEWER_IDENTITY" in caplog.text


def test_unknown_review_is_404(env):
    assert env.post(review="nope").json()["detail"]["reason_code"] == "REVIEW_NOT_FOUND"


def test_refusal_is_409_with_the_reason(env):
    env.config = PostingConfig()
    response = env.post()
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "POSTING_DISABLED"


def test_basecamp_unreachable_is_502_with_the_error_class_and_the_review_stays_pending(env):
    env.thread.get_failures = [httpx.ConnectError("down")] * 3
    response = env.post()
    assert response.status_code == 502
    assert response.json()["detail"]["reason_code"] == "UpstreamUnavailable"
    assert env.queue.get_by_review_id(REVIEW).status == "Pending"


def test_missing_basecamp_settings_fail_clearly_without_a_crash(env):
    def no_config():
        raise BasecampConfigError("BASECAMP_ACCESS_TOKEN is missing or blank")
    env.client_factory = no_config
    response = env.post()
    assert response.status_code == 502 and response.json()["detail"]["reason_code"] == "ConfigError"


def test_audit_trail_down_is_503_retry(env):
    class Failing(InMemoryAuditTrail):
        def record(self, event):
            raise AuditWriteError("disk full")
    env.audit = Failing()
    response = env.post()
    assert response.status_code == 503 and "Retry" in response.json()["detail"]["message"]


def test_bad_posting_settings_are_503_naming_the_variable(monkeypatch):
    monkeypatch.setenv("BASECAMP_POSTING_ENABLED", "maybe")
    app.dependency_overrides.clear()
    response = TestClient(app).post(f"/reviews/{REVIEW}/post", headers=REQUESTER)
    assert response.status_code == 503
    assert "BASECAMP_POSTING_ENABLED" in response.json()["detail"]["message"]
