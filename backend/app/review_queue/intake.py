"""Critique intake (STORY-001: REQ-001 + REQ-002).

Takes one raw Basecamp comment row, validates it, runs marker detection and,
when a valid marker is present, creates a Pending Review Queue item tied to
that exact comment version. Every outcome writes one structured JSON log line
carrying the exact comment_id, so any review can be traced back to the
comment that triggered it.

Failure modes handled here: malformed row (logged, no item), comment without
a valid marker (logged, no item), duplicate processing (existing item
returned, no second item). run_intake adds the source-unreachable path:
fetching is retried with a cap (see comment_source.fetch_with_retry) and, if
it still fails, CommentSourceUnavailable propagates and the queue is untouched.

Audit trail (STORY-011): every outcome above is also recorded as an AuditEvent.
The trail is a required argument, so no caller can process a comment without
one. If the audit write fails, AuditWriteError is logged and re-raised and no
result is returned, so the caller never treats an unrecorded action as done.
For "review_created" the event is written right after the item is created; if
that write fails the item stays in the queue, and re-running intake (safe, it
never duplicates) records "review_already_queued" for it.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import ValidationError

from app.audit.trail import AuditTrail, AuditWriteError
from app.basecamp.comment_source import CommentSource, fetch_with_retry
from app.basecamp.critique_marker_detector import is_critique_marker
from app.models import AuditEvent, BasecampComment, IntakeResult
from app.review_queue.store import ReviewQueueStore

logger = logging.getLogger("stress_test_review.intake")


# Intake runs unattended, so its audit entries are recorded under this actor.
SYSTEM_ACTOR_ID = "system"

_AUDIT_ACTIONS = {
    "review_created": "review_created",
    "already_queued": "review_already_queued",
    "no_marker": "comment_no_marker",
    "malformed": "comment_rejected_malformed",
}


def process_comment(
    raw: Any,
    store: ReviewQueueStore,
    audit: AuditTrail,
    correlation_id: Optional[str] = None,
) -> IntakeResult:
    correlation_id = correlation_id or str(uuid.uuid4())
    try:
        comment = BasecampComment.model_validate(raw)
    except ValidationError as exc:
        comment_id = _readable_comment_id(raw)
        _log(
            logging.WARNING,
            "comment_rejected_malformed",
            correlation_id,
            comment_id=comment_id,
            outcome="failure",
            error_class="ValidationError",
            invalid_fields=sorted({str(err["loc"][0]) for err in exc.errors() if err["loc"]}),
        )
        result = IntakeResult(outcome="malformed", comment_id=comment_id)
        _record(audit, result, correlation_id, outcome="failure", reason_code="ValidationError")
        return result

    if not is_critique_marker(comment.body):
        _log(
            logging.INFO,
            "critique_marker_not_found",
            correlation_id,
            comment_id=comment.comment_id,
            message_id=comment.message_id,
            outcome="success",
        )
        result = IntakeResult(outcome="no_marker", comment_id=comment.comment_id)
        _record(audit, result, correlation_id, message_id=comment.message_id)
        return result

    item, created = store.create_pending(comment)
    outcome = "review_created" if created else "already_queued"
    _log(
        logging.INFO,
        "critique_marker_detected",
        correlation_id,
        comment_id=comment.comment_id,
        message_id=comment.message_id,
        review_id=item.review_id,
        review_status=item.status,
        outcome="success",
        intake_outcome=outcome,
    )
    result = IntakeResult(outcome=outcome, comment_id=comment.comment_id, review_id=item.review_id)
    _record(audit, result, correlation_id, message_id=comment.message_id)
    return result


def run_intake(
    source: CommentSource,
    store: ReviewQueueStore,
    audit: AuditTrail,
    correlation_id: Optional[str] = None,
) -> List[IntakeResult]:
    """Fetch comments (bounded retries) and process each one. Raises
    CommentSourceUnavailable if the source stays unreachable; safe to re-run
    because process_comment is idempotent per comment_id."""
    correlation_id = correlation_id or str(uuid.uuid4())
    rows = fetch_with_retry(source)
    return [process_comment(row, store, audit, correlation_id) for row in rows]


def _record(
    audit: AuditTrail,
    result: IntakeResult,
    correlation_id: str,
    outcome: str = "success",
    message_id: Optional[int] = None,
    reason_code: Optional[str] = None,
) -> None:
    event = AuditEvent(
        event_id=str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc),
        action=_AUDIT_ACTIONS[result.outcome],
        actor_id=SYSTEM_ACTOR_ID,
        outcome=outcome,
        correlation_id=correlation_id,
        comment_id=result.comment_id,
        message_id=message_id,
        review_id=result.review_id,
        reason_code=reason_code,
    )
    try:
        audit.record(event)
    except AuditWriteError:
        _log(
            logging.ERROR,
            "audit_write_failed",
            correlation_id,
            comment_id=result.comment_id,
            review_id=result.review_id,
            audit_action=event.action,
            outcome="failure",
            error_class=AuditWriteError.error_class,
        )
        raise


def _readable_comment_id(raw: Any) -> Optional[int]:
    """Best-effort id for logging a malformed row. Only a real integer is
    echoed back, so arbitrary untrusted values never land in the log."""
    if isinstance(raw, dict):
        value = raw.get("comment_id")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _log(level: int, event: str, correlation_id: str, **context: Any) -> None:
    line = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": logging.getLevelName(level).lower(),
        "service": "backend",
        "event": event,
        "correlation_id": correlation_id,
        **context,
    }
    logger.log(level, json.dumps(line))
