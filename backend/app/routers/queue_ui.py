"""Review Queue web UI routes (STORY-012, REQ-018): the queue list and one
review's detail with its status and history. Read-only; every call is
audited (see app/queue_ui/viewing.py).

Reviewer identity: the signed-in Basecamp user's email (STORY-014,
app/auth/guards.py).

Status codes: 401 not signed in; 404 unknown review;
409 the saved reviewer actions no longer fit the newest AI draft;
503 a store or the audit trail cannot be read/written ("could not load,
retry"; retrying is safe, nothing is written except the audit event).
"""
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditTrail, AuditWriteError
from app.auth.guards import require_signed_in
from app.auth.sessions import Principal
from app.human_review.dependencies import get_draft_source, get_review_action_store
from app.human_review.drafts import DraftSource
from app.human_review.store import ReviewActionStore
from app.models import MAX_ID_LENGTH
from app.posting.dependencies import get_posting_store
from app.posting.store import PostingStore
from app.queue_ui import service, viewing
from app.queue_ui.models import QueueRow, ReviewDetail
from app.review_queue.dependencies import get_review_queue_store
from app.review_queue.store import ReviewQueueStore

router = APIRouter(prefix="/queue-ui", tags=["review queue ui"])

Reviewer = Depends(require_signed_in)
CorrelationHeader = Header(default=None, max_length=64)


@router.get("/reviews", response_model=List[QueueRow])
def get_queue(queue: ReviewQueueStore = Depends(get_review_queue_store),
              drafts: DraftSource = Depends(get_draft_source),
              actions: ReviewActionStore = Depends(get_review_action_store),
              postings: PostingStore = Depends(get_posting_store),
              audit: AuditTrail = Depends(get_audit_trail),
              reviewer: Principal = Reviewer,
              x_correlation_id: Optional[str] = CorrelationHeader) -> List[QueueRow]:
    return _run(lambda: viewing.view_queue(
        reviewer.email, x_correlation_id or str(uuid.uuid4()), audit,
        lambda: service.list_rows(queue, drafts, actions, postings)))


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
def get_review(review_id: str, drafts: DraftSource = Depends(get_draft_source),
               actions: ReviewActionStore = Depends(get_review_action_store),
               postings: PostingStore = Depends(get_posting_store),
               audit: AuditTrail = Depends(get_audit_trail),
               reviewer: Principal = Reviewer,
               x_correlation_id: Optional[str] = CorrelationHeader) -> ReviewDetail:
    return _run(lambda: viewing.view_review(
        review_id[:MAX_ID_LENGTH], reviewer.email, x_correlation_id or str(uuid.uuid4()), audit,
        lambda: service.review_detail(review_id, drafts, actions, postings)))


def _run(call):
    try:
        return call()
    except viewing.ViewerRefused as exc:
        status = 401 if exc.reason_code == "MISSING_REVIEWER_IDENTITY" else 403
        raise HTTPException(status, {"reason_code": exc.reason_code, "message": str(exc)}) from exc
    except service.ReviewNotInQueue as exc:
        raise HTTPException(404, {"reason_code": exc.reason_code, "message": str(exc)}) from exc
    except service.ReviewStateMismatch as exc:
        raise HTTPException(409, {"reason_code": exc.reason_code, "message": str(exc)}) from exc
    except (service.QueueReadError, AuditWriteError) as exc:
        raise HTTPException(503, {
            "error_class": exc.error_class,
            "reason_code": getattr(exc, "reason_code", None),
            "message": "Could not load the Review Queue: storage or the audit trail is unavailable. Retry; it is safe.",
        }) from exc
