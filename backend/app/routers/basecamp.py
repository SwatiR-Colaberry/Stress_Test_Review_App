from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditTrail, AuditWriteError
from app.basecamp.critique_marker_detector import normalize_critique_marker
from app.models import BasecampComment, IntakeResult, MarkerDetectRequest, MarkerDetectResponse
from app.review_queue.dependencies import get_review_queue_store
from app.review_queue.intake import process_comment
from app.review_queue.store import ReviewQueueStore

router = APIRouter(prefix="/basecamp", tags=["basecamp"])


@router.post("/critique-marker/detect", response_model=MarkerDetectResponse)
def detect_marker(body: MarkerDetectRequest) -> MarkerDetectResponse:
    """Read-only REQ-001 check over a bare comment body. Creates nothing;
    use POST /basecamp/comments/process to run full intake (REQ-002)."""
    normalized = normalize_critique_marker(body.comment_body)
    return MarkerDetectResponse(is_critique_marker=normalized is not None, normalized_marker=normalized)


@router.post("/comments/process", response_model=IntakeResult)
def process_basecamp_comment(
    comment: BasecampComment,
    store: ReviewQueueStore = Depends(get_review_queue_store),
    audit: AuditTrail = Depends(get_audit_trail),
    x_correlation_id: Optional[str] = Header(default=None, max_length=64),
) -> IntakeResult:
    """STORY-001: detect the critique marker and, if present, create a Pending
    Review Queue item for this exact comment version. Idempotent per
    comment_id. Malformed bodies are rejected with 422 before reaching intake.
    An X-Correlation-ID header, if sent, is carried into the log line.

    STORY-011: the outcome is recorded in the audit trail. If that write
    fails, the caller gets 503 (not a result), so nothing is reported as
    processed without a record; retrying is safe."""
    try:
        return process_comment(comment.model_dump(), store, audit, correlation_id=x_correlation_id)
    except AuditWriteError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error_class": exc.error_class, "message": "Audit trail unavailable; the outcome was not recorded. Retry: processing this comment again is safe and does not duplicate it."},
        ) from exc
