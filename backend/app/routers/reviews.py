from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.guardrails.review_finalization_guardrail import (
    UnsafeFinalizationError,
    assert_safe_to_finalize,
)
from app.models import FinalizeCheckResponse, ReviewItem, StressTestReview
from app.review_queue.dependencies import get_review_queue_store
from app.review_queue.store import ReviewQueueStore

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("/finalize-check", response_model=FinalizeCheckResponse)
def finalize_check(review: StressTestReview) -> FinalizeCheckResponse:
    """Read-only: does this review pass REQ-011's human-approval gate?

    Does not mutate anything and does not itself finalize or post to
    Basecamp — that path doesn't exist yet (Phase 4, blocked on the
    Basecamp integration). This lets the same gate be exercised over HTTP
    today and reused unchanged once that path is built.
    """
    try:
        assert_safe_to_finalize(review)
    except UnsafeFinalizationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"reason_code": exc.reason_code, "message": str(exc)},
        ) from exc
    return FinalizeCheckResponse(safe=True)


@router.get("/queue", response_model=List[ReviewItem])
def review_queue(store: ReviewQueueStore = Depends(get_review_queue_store)) -> List[ReviewItem]:
    """Every Review Queue item, oldest comment version first (REQ-002)."""
    return store.list_items()
