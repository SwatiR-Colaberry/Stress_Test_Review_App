import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditTrail, AuditWriteError
from app.guardrails.review_finalization_guardrail import (
    UnsafeFinalizationError,
    assert_safe_to_finalize,
)
from app.models import AuditEvent, FinalizeCheckResponse, ReviewItem, StressTestReview
from app.review_queue.dependencies import get_review_queue_store
from app.review_queue.store import ReviewQueueStore

router = APIRouter(prefix="/reviews", tags=["reviews"])

# Recorded as the actor when a finalize attempt names no reviewer at all.
UNIDENTIFIED_ACTOR_ID = "unidentified"


@router.post("/finalize-check", response_model=FinalizeCheckResponse)
def finalize_check(
    review: StressTestReview,
    audit: AuditTrail = Depends(get_audit_trail),
    x_correlation_id: Optional[str] = Header(default=None, max_length=64),
) -> FinalizeCheckResponse:
    """Read-only: does this review pass REQ-011's human-approval gate?

    Does not mutate anything and does not itself finalize or post to
    Basecamp — that path doesn't exist yet (Phase 4, blocked on the
    Basecamp integration). This lets the same gate be exercised over HTTP
    today and reused unchanged once that path is built.

    STORY-011: every attempt is recorded in the audit trail, allowed
    (finalize_allowed) or blocked (finalize_blocked + reason code). The
    event is written before the answer is returned; if it cannot be
    written the request fails with 503, so an approval is never allowed
    without a record.
    """
    try:
        assert_safe_to_finalize(review)
    except UnsafeFinalizationError as exc:
        _record_finalize_attempt(audit, review, x_correlation_id, blocked_reason=exc.reason_code)
        raise HTTPException(
            status_code=409,
            detail={"reason_code": exc.reason_code, "message": str(exc)},
        ) from exc
    _record_finalize_attempt(audit, review, x_correlation_id, blocked_reason=None)
    return FinalizeCheckResponse(safe=True)


@router.get("/queue", response_model=List[ReviewItem])
def review_queue(store: ReviewQueueStore = Depends(get_review_queue_store)) -> List[ReviewItem]:
    """Every Review Queue item, oldest comment version first (REQ-002)."""
    return store.list_items()


def _record_finalize_attempt(
    audit: AuditTrail,
    review: StressTestReview,
    correlation_id: Optional[str],
    blocked_reason: Optional[str],
) -> None:
    decision = review.reviewer_decision
    reviewer_id = (decision.reviewer_id or "").strip() if decision else ""
    event = AuditEvent(
        event_id=str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc),
        action="finalize_blocked" if blocked_reason else "finalize_allowed",
        actor_id=reviewer_id or UNIDENTIFIED_ACTOR_ID,
        outcome="blocked" if blocked_reason else "success",
        correlation_id=correlation_id or str(uuid.uuid4()),
        review_id=review.review_id,
        reason_code=blocked_reason,
    )
    try:
        audit.record(event)
    except AuditWriteError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error_class": exc.error_class,
                "message": "Audit trail unavailable; the finalize check was not recorded, so it is refused. Retry later.",
            },
        ) from exc
