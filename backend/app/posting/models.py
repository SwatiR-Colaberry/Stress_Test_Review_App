"""Contracts for posting final feedback to Basecamp (STORY-006, REQ-007).

A PostingRecord is one line of data/reviews/posted.jsonl: what happened to one
review's feedback at one moment. Records are appended, never changed, so the
file is the posting history (REQ-008). The latest record for a review is its
current posting state.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import MAX_ID_LENGTH, BasecampId, ReviewStatus

# "posting": about to call Basecamp. "posted": Basecamp confirmed the comment
# (the only state that lets the review become Completed). "failed": gave up;
# a later request may try again.
PostingStatus = Literal["posting", "posted", "failed"]

# Short stable code that names why posting stopped, e.g. "PROJECT_NOT_ALLOWED"
# or an error class such as "UpstreamUnavailable". Never free text.
ReasonCode = Field(default=None, max_length=64, pattern=r"^[A-Za-z_]+$")


class PostingTarget(BaseModel):
    """The Basecamp thread the feedback is posted to."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: BasecampId
    message_id: BasecampId

    def comments_path(self) -> str:
        return f"/buckets/{self.project_id}/recordings/{self.message_id}/comments.json"


class PostingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(pattern=r"^FB-[0-9a-f]{12}$")
    review_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    status: PostingStatus
    recorded_at: datetime
    attempt: int = Field(ge=0)  # 0 = refused before any Basecamp call
    basecamp_comment_id: Optional[BasecampId] = None
    reason_code: Optional[str] = ReasonCode


class PostingResult(BaseModel):
    """What one posting request did. status "posted" is the only one after
    which the review is Completed."""
    review_id: str
    feedback_id: str
    status: Literal["posted", "failed", "refused"]
    already_posted: bool = False  # true: an earlier request (or attempt) posted it; nothing sent now
    attempts: int = 0
    basecamp_comment_id: Optional[int] = None
    reason_code: Optional[str] = None
    review_status: ReviewStatus  # the Review Queue status after this request
