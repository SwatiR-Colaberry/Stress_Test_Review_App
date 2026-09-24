"""Pydantic models — the typed contract for the API (REQ-015) and the shared
shape guardrails and routers agree on. Formalizes what used to be JSDoc
@typedef comments (documentation only, not enforced) as real, validated types.
"""
from datetime import datetime
from typing import List, Optional
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ReviewerDecision(BaseModel):
    reviewer_id: Optional[str] = None
    outcome: Optional[Literal["approved", "rejected", "pending"]] = None
    decided_at: Optional[str] = None


class StressTestReview(BaseModel):
    review_id: str
    final_feedback_text: Optional[str] = None
    ai_draft_author_id: Optional[str] = None
    reviewer_decision: Optional[ReviewerDecision] = None


class FinalizeCheckResponse(BaseModel):
    safe: bool


class CredentialFinding(BaseModel):
    pattern: str
    line: int


class ScanTextRequest(BaseModel):
    content: str
    source_label: Optional[str] = None


class ScanTextResponse(BaseModel):
    safe: bool
    findings: List[CredentialFinding] = []


class MarkerDetectRequest(BaseModel):
    comment_body: str


class MarkerDetectResponse(BaseModel):
    is_critique_marker: bool
    normalized_marker: Optional[str] = None


# Strict: a Basecamp id must arrive as a real positive integer. Lax parsing would
# turn True into 1 or " 77 " into 77 and tie a review to the wrong comment.
BasecampId = Annotated[int, Field(strict=True, gt=0)]


class BasecampComment(BaseModel):
    """One row of Basecamp_MessageBoards_MessageComments (Master Spec §4-5).

    comment_id is the exact submission/version identity; message_id is the
    overall thread. Missing or non-positive ids fail validation, so malformed
    comment data never reaches detection or review creation.
    """
    comment_id: BasecampId
    message_id: BasecampId
    body: str
    created_at: datetime


# Master Spec §22. "Completed" means a human finalized the review, never "AI finished".
ReviewStatus = Literal["Pending", "In Review", "Feedback Generated", "Completed"]


class ReviewItem(BaseModel):
    """A Review Queue entry (REQ-002), tied to the exact comment version that triggered it."""
    review_id: str
    comment_id: BasecampId
    message_id: BasecampId
    status: ReviewStatus = "Pending"
    created_at: datetime


IntakeOutcome = Literal["review_created", "already_queued", "no_marker", "malformed"]


class IntakeResult(BaseModel):
    """What processing one Basecamp comment did. review_id is set only when a
    Review Queue item exists for the comment (created now or already queued)."""
    outcome: IntakeOutcome
    comment_id: Optional[int] = None
    review_id: Optional[str] = None
