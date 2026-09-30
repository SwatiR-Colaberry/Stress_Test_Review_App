"""STORY-006 acceptance and failure paths, against a fake Basecamp thread.
No real Basecamp: every request goes to httpx.MockTransport."""
import json
import logging
import time
from datetime import datetime, timezone

import httpx
import pytest

from app.audit.trail import InMemoryAuditTrail
from app.human_review.models import PreparedFeedback
from app.models import BasecampComment
from app.posting.comment import feedback_id_for
from app.posting.config import PostingConfig
from app.posting.fake import FakeThread
from app.posting.models import PostingRecord
from app.posting.service import ReviewNotFound, post_review_feedback
from app.posting.store import PostingStore
from app.review_queue.store import InMemoryReviewQueueStore

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
PROJECT, MESSAGE, REVIEW = 111, 5001, "review-1"
FEEDBACK = "1. Add the dataset link.\n2. Select one problem."
FID = feedback_id_for(REVIEW)
CONFIG = PostingConfig(enabled=True, allowed_project_ids=frozenset({PROJECT}))


class FakeReviews:
    def __init__(self, prepared):
        self._prepared = prepared

    def prepared(self, review_id):
        return self._prepared if self._prepared and self._prepared.review_id == review_id else None


def prepared(**overrides):
    fields = dict(review_id=REVIEW, reviewer_id="swati", prepared_at=NOW, feedback_text=FEEDBACK,
                  included_finding_ids=["ST0-002"], rejected_finding_ids=[], actions_applied=2)
    fields.update(overrides)
    return PreparedFeedback(**fields)


@pytest.fixture
def world(tmp_path):
    queue = InMemoryReviewQueueStore(new_id=lambda: REVIEW)
    queue.create_pending(BasecampComment(comment_id=9001, message_id=MESSAGE, body="##Critique##",
                                         created_at=NOW, project_id=PROJECT))
    return dict(queue=queue, reviews=FakeReviews(prepared()), postings=PostingStore(tmp_path),
                audit=InMemoryAuditTrail())


def post(world, thread, config=CONFIG, **kwargs):
    kwargs.setdefault("sleep", lambda s: None)
    return post_review_feedback(
        REVIEW, "swati", config=config, correlation_id="corr-1",
        client_factory=thread.client,
        **world, **kwargs)


def actions(world):
    return [e.action for e in world["audit"].read_all()]


# --- Acceptance 1: approved feedback posted -> review Completed ---------------

def test_approved_feedback_is_posted_and_the_review_is_marked_completed(world):
    thread = FakeThread()
    assert world["queue"].get_by_review_id(REVIEW).status == "Pending"
    result = post(world, thread)
    assert result.status == "posted" and result.review_status == "Completed"
    assert world["queue"].get_by_review_id(REVIEW).status == "Completed"
    [comment] = thread.comments
    assert set(thread.paths) == {f"/999999/buckets/{PROJECT}/recordings/{MESSAGE}/comments.json"}
    assert thread.requests == ["GET", "POST"]
    assert result.basecamp_comment_id == comment["id"]
    assert "1. Add the dataset link." in comment["content"]
    assert f"Review ref: {FID}" in comment["content"] and "##FeedbackGiven##" in comment["content"]
    assert [r.status for r in world["postings"].history(REVIEW)] == ["posting", "posted"]


def test_the_review_is_not_completed_when_posting_fails(world):
    result = post(world, FakeThread(post_failures=[httpx.ConnectError("down")] * 3))
    assert result.status == "failed"
    assert world["queue"].get_by_review_id(REVIEW).status == "Pending"


def test_posting_twice_posts_once(world):
    thread = FakeThread()
    first = post(world, thread)
    requests_after_first = len(thread.requests)
    second = post(world, thread)
    assert second.status == "posted" and second.already_posted
    assert second.basecamp_comment_id == first.basecamp_comment_id
    assert len(thread.requests) == requests_after_first  # nothing sent
    assert len(thread.comments) == 1
    assert actions(world).count("feedback_posted") == 1


# --- Acceptance 2: posting error -> retry -> succeeds or logs an error --------

@pytest.mark.parametrize("failure", [httpx.ConnectError("refused"), 503, 429])
def test_a_posting_error_is_retried_and_then_succeeds(world, failure):
    waits = []
    thread = FakeThread(post_failures=[failure])
    result = post(world, thread, sleep=waits.append)
    assert result.status == "posted" and result.attempts == 2
    assert len(thread.comments) == 1
    assert waits == [1.0]
    assert world["queue"].get_by_review_id(REVIEW).status == "Completed"


def test_a_post_that_landed_but_timed_out_is_found_on_retry_and_not_posted_twice(world):
    thread = FakeThread(post_failures=["land_then_timeout"])
    result = post(world, thread)
    assert result.status == "posted" and result.already_posted and result.attempts == 2
    assert len(thread.comments) == 1
    assert thread.posts() == 1


def test_basecamp_unreachable_every_time_gives_up_after_three_attempts_and_logs_an_error(world, caplog):
    caplog.set_level(logging.INFO, logger="stress_test_review.posting")
    thread = FakeThread(get_failures=[httpx.ConnectError("down")] * 3)
    result = post(world, thread)
    assert result.status == "failed" and result.reason_code == "UpstreamUnavailable" and result.attempts == 3
    errors = [json.loads(r.message) for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0]["feedback_id"] == FID and errors[0]["status"] == "failed"
    assert errors[0]["error_class"] == "UpstreamUnavailable"
    assert actions(world)[-1] == "feedback_post_failed"


@pytest.mark.parametrize("status, error_class", [(401, "AuthError"), (422, "ContractViolation")])
def test_errors_that_a_retry_cannot_fix_fail_at_once(world, status, error_class):
    thread = FakeThread(post_failures=[status])
    result = post(world, thread)
    assert result.status == "failed" and result.reason_code == error_class and result.attempts == 1


def test_a_created_comment_without_an_id_is_a_contract_error(world):
    thread = FakeThread(post_failures=[lambda request: httpx.Response(201, json={"content": "x"})])
    assert post(world, thread).reason_code == "ContractViolation"


# --- Failure path: posting exceeds the time limit ------------------------------

def test_posting_that_exceeds_the_time_limit_stops_and_is_recorded(world):
    def slow(request):
        time.sleep(1.0)
        return httpx.Response(200, json=[])
    thread = FakeThread(get_failures=[slow])
    config = PostingConfig.model_construct(enabled=True, allowed_project_ids=frozenset({PROJECT}), time_limit_s=0.2)
    started = time.monotonic()
    result = post(world, thread, config=config)
    assert time.monotonic() - started < 0.9
    assert result.status == "failed" and result.reason_code == "TimeLimitExceeded"
    assert world["queue"].get_by_review_id(REVIEW).status == "Pending"


def test_no_new_attempt_starts_once_the_time_is_used_up(world):
    ticks = iter([0.0, 0.0, 61.0])  # deadline set, attempt 1 starts, then the clock passes the limit
    thread = FakeThread(post_failures=[503])
    result = post(world, thread, clock=lambda: next(ticks, 61.0))
    assert result.status == "failed" and result.reason_code in ("UpstreamUnavailable", "TimeLimitExceeded")
    assert thread.posts() == 1


# --- Failure path: malformed feedback / not allowed: nothing is sent ----------

def test_posting_switched_off_sends_nothing(world):
    thread = FakeThread()
    result = post(world, thread, config=PostingConfig())
    assert result.status == "refused" and result.reason_code == "POSTING_DISABLED"
    assert thread.requests == []


@pytest.mark.parametrize("change, reason", [
    (lambda w: w.update(reviews=FakeReviews(None)), "NO_PREPARED_FEEDBACK"),
    (lambda w: w.update(reviews=FakeReviews(prepared(reviewer_id="claude"))), "REVIEWER_NOT_HUMAN"),
])
def test_malformed_feedback_is_refused_before_any_basecamp_call(world, change, reason):
    change(world)
    thread = FakeThread()
    result = post(world, thread)
    assert result.status == "refused" and result.reason_code == reason
    assert thread.requests == []
    assert world["queue"].get_by_review_id(REVIEW).status == "Pending"


def test_a_project_not_on_the_posting_list_is_refused(world):
    thread = FakeThread()
    config = PostingConfig(enabled=True, allowed_project_ids=frozenset({222}))
    assert post(world, thread, config=config).reason_code == "PROJECT_NOT_ALLOWED"
    assert thread.requests == []


def test_an_unknown_review_is_not_found(world):
    with pytest.raises(ReviewNotFound):
        post_review_feedback("nope", "swati", config=CONFIG, correlation_id="c", client_factory=None, **world)


# --- Trust: every posting event carries the feedback id and status -------------

def test_every_posting_event_is_audited_with_feedback_id_and_status(world, caplog):
    caplog.set_level(logging.INFO, logger="stress_test_review.posting")
    post(world, FakeThread(post_failures=[503]))
    events = world["audit"].read_all()
    assert [e.action for e in events] == ["feedback_post_attempted", "feedback_post_attempted", "feedback_posted"]
    assert all(e.feedback_id == FID and e.review_id == REVIEW and e.actor_id == "swati" for e in events)
    assert all(e.project_id == PROJECT and e.message_id == MESSAGE for e in events)
    lines = [json.loads(r.message) for r in caplog.records if r.name == "stress_test_review.posting"]
    assert [line["status"] for line in lines] == ["posting", "retrying", "posting", "posted"]
    assert all(line["feedback_id"] == FID and line["correlation_id"] == "corr-1" for line in lines)
    assert "dataset link" not in caplog.text  # never the feedback text


def test_refusals_and_failures_are_audited_with_the_reason(world):
    post(world, FakeThread(), config=PostingConfig())
    [event] = world["audit"].read_all()
    assert (event.action, event.outcome, event.reason_code, event.feedback_id) == \
        ("feedback_post_refused", "blocked", "POSTING_DISABLED", FID)


# --- Recovery after a crash -----------------------------------------------------

def test_a_restart_after_posting_still_completes_the_review_without_posting_again(world):
    world["postings"].append(PostingRecord(feedback_id=FID, review_id=REVIEW, status="posted",
                                           recorded_at=NOW, attempt=1, basecamp_comment_id=90000))
    thread = FakeThread()
    result = post(world, thread)
    assert result.already_posted and result.review_status == "Completed"
    assert thread.requests == []
    assert actions(world) == ["feedback_posted"]  # the missing event is written once


def test_an_unexpected_error_is_recorded_and_raised(world):
    def boom(request):
        raise RuntimeError("bug")
    with pytest.raises(RuntimeError):
        post(world, FakeThread(get_failures=[boom]))
    assert world["postings"].latest(REVIEW).reason_code == "UnexpectedError"
    assert actions(world)[-1] == "feedback_post_failed"


def test_two_requests_at_the_same_moment_post_once(world):
    import threading

    started = threading.Barrier(2)

    def slow_empty_thread(request):
        time.sleep(0.2)  # both requests read the thread before either posts
        return httpx.Response(200, json=thread.comments)
    thread = FakeThread(get_failures=[slow_empty_thread, slow_empty_thread])
    results = []

    def run():
        started.wait()
        results.append(post(world, thread))
    workers = [threading.Thread(target=run) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)
    assert [r.status for r in results] == ["posted", "posted"]
    assert len(thread.comments) == 1
    assert thread.posts() == 1


def test_a_later_refusal_record_does_not_hide_an_earlier_post(world):
    world["postings"].append(PostingRecord(feedback_id=FID, review_id=REVIEW, status="posted",
                                           recorded_at=NOW, attempt=1, basecamp_comment_id=90000))
    world["postings"].append(PostingRecord(feedback_id=FID, review_id=REVIEW, status="failed",
                                           recorded_at=NOW, attempt=0, reason_code="POSTING_IN_PROGRESS"))
    thread = FakeThread()
    result = post(world, thread)
    assert result.already_posted and result.basecamp_comment_id == 90000
    assert thread.requests == []


def test_a_request_that_cannot_get_the_review_lock_in_time_is_refused(world):
    from app.posting import service

    config = PostingConfig.model_construct(enabled=True, allowed_project_ids=frozenset({111}), time_limit_s=0.1)
    lock = service._review_lock(REVIEW)
    lock.acquire()
    try:
        result = post(world, FakeThread(), config=config)
    finally:
        lock.release()
    assert result.status == "refused" and result.reason_code == "POSTING_IN_PROGRESS"
