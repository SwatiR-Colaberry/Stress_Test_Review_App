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
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import ValidationError

from app.basecamp.comment_source import CommentSource, fetch_with_retry
from app.basecamp.critique_marker_detector import is_critique_marker
from app.models import BasecampComment, IntakeResult
from app.review_queue.store import ReviewQueueStore

logger = logging.getLogger("stress_test_review.intake")


def process_comment(
    raw: Any, store: ReviewQueueStore, correlation_id: Optional[str] = None
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
        return IntakeResult(outcome="malformed", comment_id=comment_id)

    if not is_critique_marker(comment.body):
        _log(
            logging.INFO,
            "critique_marker_not_found",
            correlation_id,
            comment_id=comment.comment_id,
            message_id=comment.message_id,
            outcome="success",
        )
        return IntakeResult(outcome="no_marker", comment_id=comment.comment_id)

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
    return IntakeResult(outcome=outcome, comment_id=comment.comment_id, review_id=item.review_id)


def run_intake(
    source: CommentSource, store: ReviewQueueStore, correlation_id: Optional[str] = None
) -> List[IntakeResult]:
    """Fetch comments (bounded retries) and process each one. Raises
    CommentSourceUnavailable if the source stays unreachable; safe to re-run
    because process_comment is idempotent per comment_id."""
    correlation_id = correlation_id or str(uuid.uuid4())
    rows = fetch_with_retry(source)
    return [process_comment(row, store, correlation_id) for row in rows]


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
