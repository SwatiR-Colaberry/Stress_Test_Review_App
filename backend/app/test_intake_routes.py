import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.review_queue.dependencies import get_review_queue_store
from app.review_queue.store import InMemoryReviewQueueStore


@pytest.fixture
def client():
    store = InMemoryReviewQueueStore()
    app.dependency_overrides[get_review_queue_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _comment(body, comment_id=1001):
    return {"comment_id": comment_id, "message_id": 500, "body": body, "created_at": "2026-09-24T12:00:00Z"}


def test_critique_comment_creates_a_pending_item_visible_in_the_queue(client):
    response = client.post("/basecamp/comments/process", json=_comment("V2 ready ##Critique##"))
    assert response.status_code == 200
    assert response.json()["outcome"] == "review_created"
    queue = client.get("/reviews/queue").json()
    assert [(i["comment_id"], i["status"]) for i in queue] == [(1001, "Pending")]
    assert queue[0]["review_id"] == response.json()["review_id"]


def test_correlation_id_header_is_carried_into_the_detection_log(client, caplog):
    caplog.set_level("INFO", logger="stress_test_review.intake")
    client.post("/basecamp/comments/process", json=_comment("##Critique##", comment_id=4242), headers={"X-Correlation-ID": "abc-123"})
    [line] = [json.loads(r.getMessage()) for r in caplog.records if r.name == "stress_test_review.intake"]
    assert (line["comment_id"], line["correlation_id"]) == (4242, "abc-123")


def test_review_marker_creates_nothing(client):
    response = client.post("/basecamp/comments/process", json=_comment("## Review ##"))
    assert response.json()["outcome"] == "no_marker"
    assert client.get("/reviews/queue").json() == []


def test_malformed_comment_is_rejected_with_422_and_creates_nothing(client):
    bad = _comment("##Critique##")
    del bad["comment_id"]
    assert client.post("/basecamp/comments/process", json=bad).status_code == 422
    assert client.get("/reviews/queue").json() == []


def test_posting_the_same_comment_twice_creates_one_item(client):
    first = client.post("/basecamp/comments/process", json=_comment("##Critique##")).json()
    second = client.post("/basecamp/comments/process", json=_comment("##Critique##")).json()
    assert second["outcome"] == "already_queued"
    assert second["review_id"] == first["review_id"]
    assert len(client.get("/reviews/queue").json()) == 1
