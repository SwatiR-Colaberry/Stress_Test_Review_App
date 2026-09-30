"""Every Review Queue UI view, audited (STORY-012 trust criterion: "logs all
UI interactions with timestamps and user IDs").

Each call writes exactly one AuditEvent (recorded_at = when, actor_id = who)
and one JSON log line, whatever the outcome:
  success  the data was built; the event is written BEFORE it is returned,
           so if the audit write fails (AuditWriteError -> 503) nothing is
           shown without a record.
  blocked  no reviewer id (MISSING_REVIEWER_IDENTITY, actor "unidentified")
           or an AI/system id (AI_CANNOT_REVIEW); nothing is read.
  failure  unknown review (REVIEW_NOT_FOUND), an unreadable store
           (<STORE>_UNREADABLE), a review that no longer fits its draft
           (REVIEW_STATE_MISMATCH), or any unexpected error (its class name);
           the original error is re-raised after the event, and an audit
           failure then does not hide it (it is logged).
The reviewer page's load (GET /reviews/{id}/findings) uses view_review too,
and the Rules page (GET /rules-ui/modules) uses view_rules.
Reviewer actions, prepare and post are audited by STORY-005/006 already.

Each view is its own interaction, so event ids are fresh (uuid4): opening a
review twice is two events, by design. Reading is idempotent; only the audit
trail grows.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Optional, TypeVar

from app.audit.trail import AuditTrail, AuditWriteError
from app.evaluation.store import EvaluationStoreError
from app.guardrails.review_finalization_guardrail import AI_ACTOR_IDS
from app.human_review.service import ReviewNotFound
from app.human_review.store import ReviewStoreError
from app.models import AuditAction, AuditEvent
from app.queue_ui.models import QueueRow, ReviewDetail
from app.queue_ui.service import QueueReadError, ReviewNotInQueue, ReviewStateMismatch
from app.rules_ui.models import RulesPage
from app.rules_ui.service import RulesReadError

logger = logging.getLogger("stress_test_review.queue_ui")
UNIDENTIFIED_ACTOR_ID = "unidentified"
T = TypeVar("T")

# Load failures audited as outcome "failure": the queue UI's own, the reviewer
# page's (GET /reviews/{id}/findings, STORY-005) and the Rules page's.
# reason_code is the error's own code, else its error class.
_LOAD_FAILURES = (ReviewNotInQueue, QueueReadError, ReviewStateMismatch, ReviewNotFound, ReviewStoreError,
                  EvaluationStoreError, RulesReadError)


class ViewerRefused(Exception):
    error_class = "AuthError"

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def view_queue(viewer_id: Optional[str], correlation_id: str, audit: AuditTrail,
               build: Callable[[], List[QueueRow]]) -> List[QueueRow]:
    return _audited("queue_viewed", None, viewer_id, correlation_id, audit, build)


def view_review(review_id: str, viewer_id: Optional[str], correlation_id: str, audit: AuditTrail,
                build: Callable[[], ReviewDetail]) -> ReviewDetail:
    return _audited("review_detail_viewed", review_id, viewer_id, correlation_id, audit, build)


def view_rules(viewer_id: Optional[str], correlation_id: str, audit: AuditTrail,
               build: Callable[[], RulesPage]) -> RulesPage:
    return _audited("rules_viewed", None, viewer_id, correlation_id, audit, build)


def _audited(action: AuditAction, review_id: Optional[str], viewer_id: Optional[str], correlation_id: str,
             audit: AuditTrail, build: Callable[[], T]) -> T:
    viewer = (viewer_id or "").strip()
    refusal = _refusal(viewer)
    if refusal:
        _record(audit, action, review_id, viewer, correlation_id, "blocked", refusal.reason_code, swallow=True)
        raise refusal
    try:
        result = build()
    except _LOAD_FAILURES as exc:
        reason = getattr(exc, "reason_code", None) or exc.error_class
        _record(audit, action, review_id, viewer, correlation_id, "failure", reason, swallow=True)
        raise
    except Exception as exc:
        # Deliberately broad, and only to keep the trust criterion: an
        # unexpected error is still an interaction, so it is audited (reason =
        # its class) and then re-raised unchanged for FastAPI's 500 handling.
        _record(audit, action, review_id, viewer, correlation_id, "failure", type(exc).__name__[:64], swallow=True)
        raise
    _record(audit, action, review_id, viewer, correlation_id, "success", None, swallow=False)
    return result


def _refusal(viewer: str) -> Optional[ViewerRefused]:
    if not viewer:
        return ViewerRefused("MISSING_REVIEWER_IDENTITY", "opening a reviewer page needs a reviewer id")
    if viewer.lower() in AI_ACTOR_IDS:
        return ViewerRefused("AI_CANNOT_REVIEW", f'"{viewer}" is an AI/system identity, not a reviewer')
    return None


def _record(audit: AuditTrail, action: AuditAction, review_id: Optional[str], viewer: str, correlation_id: str,
            outcome: str, reason_code: Optional[str], swallow: bool) -> None:
    """swallow=True only on paths that already fail with their own error: the
    audit failure is logged there, never silent, and the original error wins."""
    event = AuditEvent(event_id=str(uuid.uuid4()), recorded_at=datetime.now(timezone.utc), action=action,
                       actor_id=viewer or UNIDENTIFIED_ACTOR_ID, outcome=outcome, correlation_id=correlation_id,
                       review_id=review_id, reason_code=reason_code)
    level = logging.INFO if outcome == "success" else logging.WARNING
    try:
        audit.record(event)
    except AuditWriteError as exc:
        _log(action, event, logging.ERROR, error_class=exc.error_class, audit_written=False)
        if not swallow:
            raise
        return
    _log(action, event, level, audit_written=True)


def _log(action: str, event: AuditEvent, level: int, **context) -> None:
    logger.log(level, json.dumps({
        "timestamp": event.recorded_at.isoformat(), "level": logging.getLevelName(level).lower(),
        "service": "backend", "event": action, "correlation_id": event.correlation_id,
        "outcome": event.outcome, "context": {"actor_id": event.actor_id, "review_id": event.review_id,
                                              "reason_code": event.reason_code, **context},
    }))
