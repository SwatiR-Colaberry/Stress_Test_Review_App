"""Contracts for the Review Queue web UI (STORY-012, REQ-018).

What the queue page and the review detail panel are sent. Kept out of
app/models.py to keep that file under the size ceiling; these models are part
of the same typed API contract.

The status shown is worked out when the page loads from records the app
already keeps, not read from the Review Queue item alone (user decision
2026-09-30), because the queue item stays "Pending" until a post succeeds:

    posting record "posted" or queue item "Completed"  -> Completed
    prepared feedback saved                          -> Feedback Generated
    at least one reviewer action                     -> In Review
    otherwise                                        -> Pending
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.human_review.models import PreparedFeedback, ReviewedFinding
from app.models import MAX_ID_LENGTH, ReviewStatus
from app.posting.models import PostingRecord

HistoryKind = Literal["request_received", "ai_draft", "reviewer_action", "feedback_prepared", "posting"]


class QueueRow(BaseModel):
    """One line of the queue table."""
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    status: ReviewStatus  # shown status, worked out as in the module docstring
    created_at: datetime  # when the request joined the Review Queue (intake time)
    last_activity_at: datetime  # newest history entry; created_at if none
    stress_test_id: Optional[str] = None  # from the AI draft; None until evaluated
    # Personal data from Basecamp, when known: page only, never audited or logged.
    student_name: Optional[str] = None
    basecamp_url: Optional[str] = None
    marker_note: Optional[str] = None


class HistoryEntry(BaseModel):
    """One step in a review's life, oldest first on the page.

    summary is built from codes (action kind, finding id, posting status),
    never from reviewer or student text, so it is safe to show in a list.
    actor is the reviewer id for human steps, "ai" for the draft, None for
    steps no person took (the request arriving, a posting attempt).
    """
    model_config = ConfigDict(extra="forbid")

    at: datetime
    kind: HistoryKind
    actor: Optional[str] = Field(default=None, max_length=MAX_ID_LENGTH)
    summary: str = Field(min_length=1, max_length=200)


class ReviewDetail(BaseModel):
    """Everything the detail panel shows for one review: who and where, the
    shown status, the AI draft as the reviewer currently sees it, and the full
    history (REQ-008: AI draft and human edits both kept)."""
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    status: ReviewStatus
    comment_id: int
    message_id: int
    created_at: datetime
    student_name: Optional[str] = None
    basecamp_url: Optional[str] = None
    marker_note: Optional[str] = None
    # None when the comment has not been evaluated yet ("no AI draft yet").
    stress_test_id: Optional[str] = None
    rule_version: Optional[str] = None
    findings: List[ReviewedFinding] = []
    prepared: Optional[PreparedFeedback] = None
    postings: List[PostingRecord] = []
    history: List[HistoryEntry]
