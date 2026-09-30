"""Reviewer routes (STORY-005, REQ-006): see a review's AI findings, approve /
edit / reject / add, and prepare the final feedback for Basecamp posting.
Posting itself is STORY-006.

Reviewer identity: TEMPORARY STUB. The X-Reviewer-Id header names the
reviewer; it is not verified, so anyone who can reach the API can claim any
reviewer id. AI/system and blank ids are refused. Replaced by Basecamp
sign-in (REQ-012; login story agreed 2026-09-29) before anything is posted.

Every page load is audited (review_detail_viewed, STORY-012) and needs the
reviewer id like the actions do.

Status codes: 404 unknown review or no AI draft yet; 401 no reviewer id;
403 AI/system id; 409 refused action (reason_code: UNKNOWN_FINDING,
UNDECIDED_FINDINGS, REVIEW_LOCKED, ACTION_ID_REUSED, EMPTY_FEEDBACK,
FEEDBACK_TOO_LONG); 503 storage or audit trail unavailable: "not saved,
retry" (a retry with the same action_id is safe).
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditReadError, AuditTrail, AuditWriteError
from app.evaluation.store import EvaluationStoreError
from app.human_review import service
from app.human_review.dependencies import get_draft_source, get_review_action_store
from app.human_review.drafts import DraftSource
from app.human_review.models import PreparedFeedback, ReviewerAction, ReviewView
from app.human_review.state import InvalidReviewerAction
from app.human_review.store import ReviewActionStore, ReviewStoreError
from app.models import MAX_ID_LENGTH
from app.queue_ui import viewing

router = APIRouter(prefix="/reviews", tags=["human review"])

_STATUS = {"MISSING_REVIEWER_IDENTITY": 401, "AI_CANNOT_REVIEW": 403}
_UNAVAILABLE = (ReviewStoreError, EvaluationStoreError, AuditWriteError, AuditReadError)

ReviewerHeader = Header(default=None, max_length=MAX_ID_LENGTH)
CorrelationHeader = Header(default=None, max_length=64)


@router.get("/{review_id}/findings", response_model=ReviewView)
def get_findings(review_id: str, drafts: DraftSource = Depends(get_draft_source),
                 store: ReviewActionStore = Depends(get_review_action_store),
                 audit: AuditTrail = Depends(get_audit_trail),
                 x_reviewer_id: Optional[str] = ReviewerHeader,
                 x_correlation_id: Optional[str] = CorrelationHeader) -> ReviewView:
    # STORY-012: opening the page is a UI interaction, audited as review_detail_viewed.
    return _run(lambda: viewing.view_review(review_id[:MAX_ID_LENGTH], x_reviewer_id,
                                            x_correlation_id or str(uuid.uuid4()), audit,
                                            lambda: service.view_review(review_id, drafts, store)))


@router.post("/{review_id}/actions", response_model=ReviewView)
def post_action(review_id: str, action: ReviewerAction, drafts: DraftSource = Depends(get_draft_source),
                store: ReviewActionStore = Depends(get_review_action_store),
                audit: AuditTrail = Depends(get_audit_trail),
                x_reviewer_id: Optional[str] = ReviewerHeader,
                x_correlation_id: Optional[str] = CorrelationHeader) -> ReviewView:
    return _run(lambda: service.apply_action(review_id, x_reviewer_id, action, drafts, store, audit,
                                             x_correlation_id or str(uuid.uuid4())))


@router.post("/{review_id}/prepare", response_model=PreparedFeedback)
def post_prepare(review_id: str, drafts: DraftSource = Depends(get_draft_source),
                 store: ReviewActionStore = Depends(get_review_action_store),
                 audit: AuditTrail = Depends(get_audit_trail),
                 x_reviewer_id: Optional[str] = ReviewerHeader,
                 x_correlation_id: Optional[str] = CorrelationHeader) -> PreparedFeedback:
    return _run(lambda: service.prepare_feedback(review_id, x_reviewer_id, drafts, store, audit,
                                                 x_correlation_id or str(uuid.uuid4())))


def _run(call):
    try:
        return call()
    except viewing.ViewerRefused as exc:
        raise HTTPException(_STATUS[exc.reason_code], {"reason_code": exc.reason_code, "message": str(exc)}) from exc
    except service.ReviewNotFound as exc:
        raise HTTPException(404, {"reason_code": exc.reason_code, "message": str(exc)}) from exc
    except InvalidReviewerAction as exc:
        raise HTTPException(_STATUS.get(exc.reason_code, 409),
                            {"reason_code": exc.reason_code, "message": str(exc)}) from exc
    except _UNAVAILABLE as exc:
        raise HTTPException(503, {
            "error_class": exc.error_class,
            "message": "Not saved: review storage or the audit trail is unavailable. Retry; it is safe.",
        }) from exc
