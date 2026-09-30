"""Post a review's final feedback to Basecamp and only then mark it Completed
(STORY-006, REQ-007).

post_review_feedback() steps:
  1. The review must be in the Review Queue (else ReviewNotFound).
  2. Already posted (any "posted" record)? Return it, send nothing, and make
     sure the queue says Completed and the audit has feedback_posted (repairs
     a request that died after posting).
  3. Posting switched off (BASECAMP_POSTING_ENABLED) or the feedback fails
     checks.check_ready_to_post() -> "refused", audited, nothing sent.
  4. Up to max_attempts attempts. Each one first reads the thread and looks
     for this feedback's "Review ref"; only if it is not there is the comment
     posted. So a post that timed out but did land is found, never repeated.
  5. Basecamp confirmed -> "posted" record, feedback_posted audit event, then
     the queue item becomes Completed. Never before.

Failure handling:
- Basecamp unreachable / 5xx / 429 (BasecampUnavailable, BasecampRateLimited):
  retried after backoff while attempts and time remain; then "failed" with the
  error class, audited and logged as an error.
- Token rejected or unexpected Basecamp answer (AuthError, ContractViolation):
  "failed" at once; retrying cannot help.
- Time limit (BASECAMP_POSTING_TIME_LIMIT_S) covers the whole request. Each
  attempt runs in a daemon thread bounded by the time left (bounded_call); on
  expiry -> "failed" TimeLimitExceeded. The abandoned call may still post; the
  next request reads the thread first and records it instead of posting again.
- Store or audit write fails -> PostingStoreError / AuditWriteError raised
  (caller answers 503 "retry"). A retry is safe for the reason above.
- Basecamp settings missing (BasecampConfigError) -> "failed" ConfigError, nothing sent.
- Two requests for one review at once: a per-review lock makes the second
  wait, then return the first one's result (already posted); if it waits
  longer than the time limit -> "refused" POSTING_IN_PROGRESS. Per process only.
- Anything unexpected -> "failed" UnexpectedError recorded and logged, then re-raised.

Every attempt, refusal, success and failure is an audit event with the
feedback id and a JSON log line with feedback id and status (Trust criterion).
Nothing student-written or secret is logged: ids and codes only.
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Sequence, Tuple

from app.audit.trail import AuditTrail
from app.basecamp.api_client import BasecampClient, BasecampError, BasecampRateLimited, BasecampResponseError, \
    BasecampUnavailable
from app.basecamp.config import BasecampConfigError
from app.history.bounded import bounded_call
from app.human_review.store import ReviewActionStore
from app.models import AuditAction, AuditEvent, ReviewItem
from app.posting.checks import PostingRefused, check_ready_to_post
from app.posting.comment import build_comment_html, contains_feedback_id, feedback_id_for
from app.posting.config import PostingConfig
from app.posting.models import PostingRecord, PostingResult, PostingTarget
from app.posting.store import PostingStore
from app.review_queue.store import ReviewQueueStore

logger = logging.getLogger("stress_test_review.posting")

_EVENT_NAMESPACE = uuid.UUID("5f0c1d2e-0006-4a5b-9c6d-000000000006")  # fixed: ids must be stable across runs
_RETRYABLE = (BasecampUnavailable, BasecampRateLimited)

# One posting request per review at a time in this process: a second request
# waits (at most the time limit), then finds the first one's post. Between
# processes this is not guaranteed; run one server process until posting
# records move to a database with a unique key.
_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _review_lock(review_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(review_id, threading.Lock())


class ReviewNotFound(Exception):
    error_class = "ReviewNotFound"


class PostingTimeLimitExceeded(Exception):
    error_class = "TimeLimitExceeded"


def post_review_feedback(
    review_id: str,
    requested_by: str,
    *,
    queue: ReviewQueueStore,
    reviews: ReviewActionStore,
    postings: PostingStore,
    audit: AuditTrail,
    client_factory: Callable[[], BasecampClient],
    config: PostingConfig,
    correlation_id: str,
    max_attempts: int = 3,
    backoff_s: Sequence[float] = (1.0, 2.0),
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> PostingResult:
    item = queue.get_by_review_id(review_id)
    if item is None:
        _log("feedback_posting", correlation_id, logging.WARNING, review_id=review_id[:128],
             status="not_found", error_class=ReviewNotFound.error_class)
        raise ReviewNotFound(f"no review {review_id} in the Review Queue")
    run = _Run(item, requested_by, postings, audit, correlation_id)
    lock = _review_lock(review_id)
    if not lock.acquire(timeout=config.time_limit_s):
        return run.refused("POSTING_IN_PROGRESS")
    try:
        return _post_locked(run, queue, reviews, postings, client_factory, config, max_attempts, backoff_s,
                            sleep, clock)
    finally:
        lock.release()


def _post_locked(run: "_Run", queue: ReviewQueueStore, reviews: ReviewActionStore, postings: PostingStore,
                 client_factory: Callable[[], BasecampClient], config: PostingConfig, max_attempts: int,
                 backoff_s: Sequence[float], sleep: Callable[[float], None],
                 clock: Callable[[], float]) -> PostingResult:
    item, review_id = run.item, run.item.review_id
    earlier = postings.posted(review_id)
    if earlier is not None:
        return run.posted(queue, earlier.basecamp_comment_id, earlier.attempt, already_posted=True)
    if not config.enabled:
        return run.refused("POSTING_DISABLED")
    try:
        target = check_ready_to_post(item, reviews.prepared(review_id), config.allowed_project_ids)
    except PostingRefused as exc:
        return run.refused(exc.reason_code)
    body = build_comment_html(reviews.prepared(review_id).feedback_text, run.feedback_id)

    deadline = clock() + config.time_limit_s
    try:
        client = client_factory()
    except BasecampConfigError:  # names the missing variables, never values; nothing was sent
        return run.failed("ConfigError", 0)
    try:
        for attempt in range(1, max_attempts + 1):
            remaining = deadline - clock()
            if remaining <= 0:
                return run.failed(PostingTimeLimitExceeded.error_class, attempt - 1)
            run.attempted(attempt)
            try:
                comment_id, found = bounded_call(
                    lambda: _post_once(client, target, body, run.feedback_id),
                    what="basecamp_post", error=PostingTimeLimitExceeded,
                    timeout_s=remaining, attempts=1, no_retry=(Exception,))
            except PostingTimeLimitExceeded:
                return run.failed(PostingTimeLimitExceeded.error_class, attempt)
            except _RETRYABLE as exc:
                wait = backoff_s[min(attempt - 1, len(backoff_s) - 1)]
                if attempt == max_attempts or clock() + wait >= deadline:
                    return run.failed(exc.error_class, attempt)
                run.will_retry(exc.error_class, attempt)
                sleep(wait)
                continue
            except BasecampError as exc:
                return run.failed(exc.error_class, attempt)
            except Exception:
                run.failed("UnexpectedError", attempt)
                raise
            return run.posted(queue, comment_id, attempt, already_posted=found)
    finally:
        client.close()
    raise AssertionError("unreachable")  # the loop always returns or raises


def _post_once(client: BasecampClient, target: PostingTarget, body: str, feedback_id: str) -> Tuple[int, bool]:
    """Returns (Basecamp comment id, found_already). Reads the thread first so
    a comment that landed on an earlier attempt is never posted again."""
    path = target.comments_path()
    for comment in client.get_all(path):
        if isinstance(comment, dict) and contains_feedback_id(str(comment.get("content") or ""), feedback_id):
            return _comment_id(comment), True
    return _comment_id(client.post_json(path, {"content": body})), False


def _comment_id(comment: dict) -> int:
    value = comment.get("id")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise BasecampResponseError("Basecamp comment has no valid id")
    return value


class _Run:
    """One posting request: writes its records, audit events and log lines."""

    def __init__(self, item: ReviewItem, requested_by: str, postings: PostingStore, audit: AuditTrail,
                 correlation_id: str) -> None:
        self.item = item
        self.feedback_id = feedback_id_for(item.review_id)
        self.actor = (requested_by or "").strip()[:128] or "unidentified"
        self._postings = postings
        self._audit = audit
        self._correlation_id = correlation_id

    def refused(self, reason: str) -> PostingResult:
        self._record("failed", 0, reason_code=reason)
        self._event("feedback_post_refused", "blocked", reason_code=reason)
        self._log("refused", logging.WARNING, reason_code=reason, error_class="ValidationError")
        return self._result("refused", 0, reason_code=reason)

    def attempted(self, attempt: int) -> None:
        self._record("posting", attempt)
        self._event("feedback_post_attempted", "success")
        self._log("posting", attempt=attempt)

    def will_retry(self, error_class: str, attempt: int) -> None:
        self._log("retrying", logging.WARNING, attempt=attempt, error_class=error_class)

    def failed(self, error_class: str, attempts: int) -> PostingResult:
        self._record("failed", attempts, reason_code=error_class)
        self._event("feedback_post_failed", "failure", reason_code=error_class)
        self._log("failed", logging.ERROR, attempts=attempts, error_class=error_class)
        return self._result("failed", attempts, reason_code=error_class)

    def posted(self, queue: ReviewQueueStore, comment_id: Optional[int], attempts: int,
               already_posted: bool) -> PostingResult:
        if self._postings.posted(self.item.review_id) is None:
            self._record("posted", attempts, basecamp_comment_id=comment_id)
        # Stable id: a retried request writes the event only if it is missing.
        event_id = str(uuid.uuid5(_EVENT_NAMESPACE, f"{self.item.review_id}:posted"))
        if not any(e.event_id == event_id for e in self._audit.read_all()):
            self._event("feedback_posted", "success", event_id=event_id)
        completed = queue.mark_completed(self.item.review_id)  # REQ-007: only after Basecamp confirmed
        self._log("posted", attempts=attempts, basecamp_comment_id=comment_id, already_posted=already_posted)
        return self._result("posted", attempts, basecamp_comment_id=comment_id, already_posted=already_posted,
                            review_status=completed.status if completed else self.item.status)

    def _record(self, status: str, attempt: int, **fields) -> None:
        self._postings.append(PostingRecord(
            feedback_id=self.feedback_id, review_id=self.item.review_id, status=status,
            recorded_at=datetime.now(timezone.utc), attempt=attempt, **fields))

    def _event(self, action: AuditAction, outcome: str, event_id: Optional[str] = None, **fields) -> None:
        self._audit.record(AuditEvent(
            event_id=event_id or str(uuid.uuid4()), recorded_at=datetime.now(timezone.utc), action=action,
            actor_id=self.actor, outcome=outcome, correlation_id=self._correlation_id,
            review_id=self.item.review_id, comment_id=self.item.comment_id, message_id=self.item.message_id,
            project_id=self.item.project_id, feedback_id=self.feedback_id, **fields))

    def _result(self, status: str, attempts: int, review_status: Optional[str] = None, **fields) -> PostingResult:
        return PostingResult(review_id=self.item.review_id, feedback_id=self.feedback_id, status=status,
                             attempts=attempts, review_status=review_status or self.item.status, **fields)

    def _log(self, status: str, level: int = logging.INFO, **context) -> None:
        _log("feedback_posting", self._correlation_id, level, review_id=self.item.review_id,
             feedback_id=self.feedback_id, status=status, **context)


def _log(event: str, correlation_id: str, level: int = logging.INFO, **context) -> None:
    logger.log(level, json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(), "level": logging.getLevelName(level).lower(),
        "service": "backend", "event": event, "correlation_id": correlation_id,
        "outcome": "failure" if level >= logging.WARNING else "success", **context,
    }))
