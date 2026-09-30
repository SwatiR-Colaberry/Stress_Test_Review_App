"""The STORY-012 demo's seed gives one review per stage, through the real
routes, against temporary stores only (never data/)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.audit.dependencies import get_audit_trail
from app.audit.trail import InMemoryAuditTrail
from app.evaluation.store import ResultStore
from app.human_review.dependencies import get_draft_source, get_review_action_store
from app.human_review.drafts import DraftSource
from app.human_review.store import ReviewActionStore
from app.main import app
from app.posting.dependencies import get_posting_store
from app.posting.store import PostingStore
from app.review_queue.dependencies import get_review_queue_store
from app.review_queue.store import InMemoryReviewQueueStore

sys.path.insert(0, str(Path(__file__).resolve().parent))
import queue_ui_demo  # noqa: E402


def test_the_demo_seeds_one_review_per_stage(tmp_path):
    queue, audit = InMemoryReviewQueueStore(), InMemoryAuditTrail()
    postings = PostingStore(tmp_path / "reviews")
    app.dependency_overrides.update({
        get_review_queue_store: lambda: queue,
        get_draft_source: lambda: DraftSource(queue, tmp_path / "evaluations"),
        get_review_action_store: lambda: ReviewActionStore(tmp_path / "reviews"),
        get_posting_store: lambda: postings,
        get_audit_trail: lambda: audit,
    })
    try:
        client = TestClient(app)
        ids = queue_ui_demo.seed(client, queue, ResultStore(tmp_path / "evaluations"), postings,
                                 datetime.now(timezone.utc))
        rows = client.get("/queue-ui/reviews", headers=queue_ui_demo.DEMO_REVIEWER).json()
    finally:
        app.dependency_overrides.clear()
    assert {r["review_id"]: r["status"] for r in rows} == {
        ids["Pending"]: "Pending", ids["In Review"]: "In Review", ids["Completed"]: "Completed"}
    assert [r["status"] for r in rows] == ["Completed", "In Review", "Pending"]  # newest request first
    assert {e.actor_id for e in audit.read_all()} == {"demo-reviewer"}
