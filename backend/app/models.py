"""Pydantic models — the typed contract for the API (REQ-015) and the shared
shape guardrails and routers agree on. Formalizes what used to be JSDoc
@typedef comments (documentation only, not enforced) as real, validated types.
"""
from datetime import datetime
from typing import List, Optional
from typing import Annotated, Literal

from pydantic import BaseModel, Field


# Longest id accepted from a caller. Bounded so an id can always be written to
# the audit trail (AuditEvent uses the same limit) and cannot flood it.
MAX_ID_LENGTH = 128


class ReviewerDecision(BaseModel):
    reviewer_id: Optional[str] = Field(default=None, max_length=MAX_ID_LENGTH)
    outcome: Optional[Literal["approved", "rejected", "pending"]] = None
    decided_at: Optional[str] = None


class StressTestReview(BaseModel):
    review_id: str = Field(max_length=MAX_ID_LENGTH)
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
    # Set when the student asked for review with a non-standard marker
    # (e.g. ##Please Critique##): the reviewer reminds them to use ##Critique##.
    marker_note: Optional[str] = None


IntakeOutcome = Literal["review_created", "already_queued", "no_marker", "malformed"]


class IntakeResult(BaseModel):
    """What processing one Basecamp comment did. review_id is set only when a
    Review Queue item exists for the comment (created now or already queued)."""
    outcome: IntakeOutcome
    comment_id: Optional[int] = None
    review_id: Optional[str] = None
    marker_note: Optional[str] = None


# --- Submission data retrieved from the Basecamp API (REQ-004, STORY-002) ---


class SubmissionAttachment(BaseModel):
    """A file embedded in Basecamp rich text as <bc-attachment>. @mentions use
    the same tag and are NOT attachments; the extractor leaves them out."""
    filename: Optional[str] = None
    content_type: Optional[str] = None
    url: Optional[str] = None
    sgid: Optional[str] = None


class SubmissionLink(BaseModel):
    """An http(s) link from an <a href> in Basecamp rich text."""
    url: str
    text: str = ""


class SubmissionComment(BaseModel):
    comment_id: BasecampId
    author_id: Optional[int] = None
    created_at: datetime
    content_html: str
    attachments: List[SubmissionAttachment] = []
    links: List[SubmissionLink] = []


class Submission(BaseModel):
    """One message on a project's message board, with everything a reviewer needs."""
    message_id: BasecampId
    title: str
    author_id: Optional[int] = None
    created_at: datetime
    content_html: str
    attachments: List[SubmissionAttachment] = []
    links: List[SubmissionLink] = []
    comments: List[SubmissionComment] = []


class SubmissionDataset(BaseModel):
    """The result of one retrieval. An empty project gives submissions == []."""
    project_id: BasecampId
    requested_by_user_id: str
    retrieved_at: datetime
    submissions: List[Submission] = []


# --- Audit trail (STORY-011: REQ-011, REQ-016) ---

# Every action the system takes on a submission. Kept as a closed list so a
# typo in a caller fails validation instead of writing an unsearchable action.
AuditAction = Literal[
    "review_created",
    "review_already_queued",
    "comment_no_marker",
    "comment_rejected_malformed",
    "finalize_allowed",
    "finalize_blocked",
    "retrieval_started",
    "retrieval_completed",
    "retrieval_failed",
    "rules_loaded",
    "rules_manual_resolution",
]


class AuditEvent(BaseModel):
    """One append-only audit trail entry: who did what, when, to which submission.

    Ids, outcomes and reason codes only. There is deliberately no free-text
    field, so comment bodies, personal data and secrets cannot end up in the
    audit trail (REQ-016).
    """
    event_id: str
    recorded_at: datetime
    action: AuditAction
    actor_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    outcome: Literal["success", "blocked", "failure"]
    correlation_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    comment_id: Optional[int] = None
    message_id: Optional[int] = None
    project_id: Optional[int] = None  # Basecamp project, for retrieval events
    stress_test_id: Optional[str] = Field(default=None, max_length=8)  # rule-loading events
    rule_version: Optional[str] = Field(default=None, max_length=16)  # rule-loading events
    review_id: Optional[str] = Field(default=None, max_length=MAX_ID_LENGTH)
    reason_code: Optional[str] = Field(default=None, max_length=64)
