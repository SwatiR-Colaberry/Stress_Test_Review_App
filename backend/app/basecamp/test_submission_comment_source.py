"""End-to-end across stories: fake Basecamp API -> STORY-002 retrieval ->
STORY-001 intake -> Pending review item, idempotent on re-run."""
from app.basecamp.api_client import BasecampClient
from app.basecamp.demo_data import DEMO_EMPTY_PROJECT, DEMO_PROJECT_WITH_SUBMISSIONS, demo_config, demo_transport
from app.basecamp.submission_comment_source import SubmissionCommentSource
from app.basecamp.submission_retrieval import retrieve_project_submissions
from app.review_queue.intake import run_intake
from app.audit.trail import InMemoryAuditTrail
from app.review_queue.store import InMemoryReviewQueueStore


def retrieve(project_id):
    with BasecampClient(demo_config(), transport=demo_transport()) as client:
        return retrieve_project_submissions(client, project_id, "reviewer-1")


def test_retrieved_comments_map_to_intake_rows():
    rows = SubmissionCommentSource(retrieve(DEMO_PROJECT_WITH_SUBMISSIONS)).fetch_comments(timeout_s=1)
    assert [(r["comment_id"], r["message_id"]) for r in rows] == [(401, 301)]
    assert "##Critique##" in rows[0]["body"]


def test_critique_comment_from_the_api_creates_one_pending_review_and_rerun_does_not_duplicate():
    store = InMemoryReviewQueueStore()
    source = SubmissionCommentSource(retrieve(DEMO_PROJECT_WITH_SUBMISSIONS))
    first = run_intake(source, store, InMemoryAuditTrail())
    second = run_intake(source, store, InMemoryAuditTrail())
    assert [r.outcome for r in first] == ["review_created"]
    assert [r.outcome for r in second] == ["already_queued"]
    assert first[0].review_id == second[0].review_id


def test_empty_project_gives_intake_nothing_to_do():
    assert run_intake(SubmissionCommentSource(retrieve(DEMO_EMPTY_PROJECT)), InMemoryReviewQueueStore(), InMemoryAuditTrail()) == []
