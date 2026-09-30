"""Post a review's final feedback to Basecamp (STORY-006, REQ-007).

POST /reviews/{review_id}/post -> PostingResult

Requester: X-Reviewer-Id header, a TEMPORARY stub like the STORY-005 routes
(not verified; replaced by STORY-014 Basecamp sign-in). Real posting stays
off (BASECAMP_POSTING_ENABLED=no) until then. The human approval that
matters (REQ-011) is the reviewer who prepared the feedback, checked again
by the service.

Status codes:
  200 posted (also when it was already posted: nothing is sent twice)
  401 no requester id
  404 review not in the Review Queue
  409 refused before any Basecamp call (reason_code: POSTING_DISABLED,
      NO_PREPARED_FEEDBACK, EMPTY_FEEDBACK, FEEDBACK_TOO_LONG,
      NO_POSTING_TARGET, PROJECT_NOT_ALLOWED, REVIEWER_NOT_HUMAN, ...)
  502 Basecamp failed after the allowed attempts or time (reason_code =
      error class, e.g. UpstreamUnavailable, TimeLimitExceeded, AuthError)
  503 settings invalid, or posting records / audit trail unavailable.
      Retrying is safe: the thread is checked before any new post.
Every non-2xx body carries a reason_code or error_class; never Basecamp's
own response text.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditReadError, AuditTrail, AuditWriteError
from app.basecamp.api_client import BasecampClient
from app.human_review.dependencies import get_review_action_store
from app.human_review.store import ReviewActionStore, ReviewStoreError
from app.models import MAX_ID_LENGTH
from app.posting.config import PostingConfig
from app.posting.dependencies import get_basecamp_client_factory, get_posting_config, get_posting_store
from app.posting.models import PostingResult
from app.posting.service import ReviewNotFound, post_review_feedback
from app.posting.store import PostingStore, PostingStoreError
from app.review_queue.dependencies import get_review_queue_store
from app.review_queue.store import ReviewQueueStore

router = APIRouter(prefix="/reviews", tags=["posting"])
logger = logging.getLogger("stress_test_review.posting")

_UNAVAILABLE = (PostingStoreError, ReviewStoreError, AuditWriteError, AuditReadError)
_STATUS = {"posted": 200, "refused": 409, "failed": 502}


@router.post("/{review_id}/post", response_model=PostingResult)
def post_feedback(
    review_id: str,
    queue: ReviewQueueStore = Depends(get_review_queue_store),
    reviews: ReviewActionStore = Depends(get_review_action_store),
    postings: PostingStore = Depends(get_posting_store),
    audit: AuditTrail = Depends(get_audit_trail),
    client_factory: Callable[[], BasecampClient] = Depends(get_basecamp_client_factory),
    config: PostingConfig = Depends(get_posting_config),
    x_reviewer_id: Optional[str] = Header(default=None, max_length=MAX_ID_LENGTH),
    x_correlation_id: Optional[str] = Header(default=None, max_length=64),
) -> PostingResult:
    if not (x_reviewer_id or "").strip():
        logger.warning(json.dumps({  # refused before the service: logged, never silent
            "timestamp": datetime.now(timezone.utc).isoformat(), "level": "warning", "service": "backend",
            "event": "feedback_posting", "correlation_id": x_correlation_id or str(uuid.uuid4()),
            "outcome": "failure", "status": "refused", "review_id": review_id[:MAX_ID_LENGTH],
            "reason_code": "MISSING_REVIEWER_IDENTITY", "error_class": "AuthError"}))
        raise HTTPException(401, {"reason_code": "MISSING_REVIEWER_IDENTITY",
                                  "message": "send X-Reviewer-Id to post feedback"})
    try:
        result = post_review_feedback(
            review_id, x_reviewer_id, queue=queue, reviews=reviews, postings=postings, audit=audit,
            client_factory=client_factory, config=config,
            correlation_id=x_correlation_id or str(uuid.uuid4()))
    except ReviewNotFound as exc:
        raise HTTPException(404, {"reason_code": "REVIEW_NOT_FOUND", "message": str(exc)}) from exc
    except _UNAVAILABLE as exc:
        raise HTTPException(503, {
            "error_class": exc.error_class,
            "message": "Posting records or the audit trail are unavailable. Retry; it is safe.",
        }) from exc
    if result.status != "posted":
        raise HTTPException(_STATUS[result.status], result.model_dump())
    return result
