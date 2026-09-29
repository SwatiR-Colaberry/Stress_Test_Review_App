"""The reviewer's contract for STORY-005 (REQ-006): approve, edit, reject or
add a finding on an AI draft before feedback is prepared for Basecamp.

Kept out of app/models.py only to keep that file under the size ceiling; these
models are part of the same typed API contract.

Length limits are the reviewer's, not the AI's. DraftFinding caps an AI
suggestion at 400 characters to bound output tokens; a reviewer must never be
forced to cut. Measured on the 2026-09-25 history extract (15 projects per
Stress Test), the longest whole reviewer reply was 4,513 characters (ST2;
median 903), so a finding may hold 2,000 and the whole prepared feedback
10,000 (user decision, 2026-09-29).
"""
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import MAX_ID_LENGTH, DraftFinding, RuleId

MAX_REVIEWER_FINDING_CHARS = 2_000
MAX_PREPARED_FEEDBACK_CHARS = 10_000

ReviewerActionKind = Literal["approve_finding", "edit_finding", "reject_finding", "add_finding"]

# Which fields each kind must carry (True) or must not carry (False).
# approve/reject decide an existing finding; edit rewrites one (and accepts it
# in the reviewer's words); add creates a finding the AI did not raise.
_SHAPE = {
    "approve_finding": {"finding_id": True, "text": False},
    "reject_finding": {"finding_id": True, "text": False},
    "edit_finding": {"finding_id": True, "text": True},
    "add_finding": {"finding_id": False, "text": True},
}


class ReviewerAction(BaseModel):
    """One reviewer action, as sent by the reviewer UI.

    action_id is the idempotency key: the UI generates it once per click and
    reuses it on retry, so a retried request never applies an action twice.
    The reviewer's identity is not in the body; the route supplies it.
    finding_id names an AI finding by its rule id (unique within one
    evaluation) or a reviewer-added finding by the id it was given.
    """
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    kind: ReviewerActionKind
    finding_id: Optional[str] = Field(default=None, min_length=1, max_length=MAX_ID_LENGTH)
    text: Optional[str] = Field(default=None, max_length=MAX_REVIEWER_FINDING_CHARS)
    # Only for add_finding: the rule the new finding is about, if any.
    rule_id: Optional[RuleId] = None

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("text must not be blank")
        return value

    @model_validator(mode="after")
    def _fields_match_kind(self) -> "ReviewerAction":
        shape = _SHAPE[self.kind]
        for field, required in shape.items():
            present = getattr(self, field) is not None
            if present != required:
                need = "requires" if required else "must not have"
                raise ValueError(f"{self.kind} {need} {field}")
        if self.rule_id is not None and self.kind != "add_finding":
            raise ValueError("rule_id is only set on add_finding")
        return self


class RecordedAction(BaseModel):
    """One line of the reviewer action log: who did what to which review, when.
    Never rewritten: together with the AI draft it is the review's full history."""
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    reviewer_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    recorded_at: datetime
    action: ReviewerAction


FindingDecision = Literal["pending", "approved", "rejected"]


class ReviewedFinding(BaseModel):
    """A finding as the reviewer currently sees it. ai_draft is the untouched
    AI finding (None for a reviewer-added one); feedback_text is what will be
    posted if the finding is approved."""
    finding_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    source: Literal["ai", "reviewer"]
    rule_id: Optional[RuleId] = None
    ai_draft: Optional[DraftFinding] = None
    decision: FindingDecision = "pending"
    feedback_text: str = Field(min_length=1, max_length=MAX_REVIEWER_FINDING_CHARS)
    edited: bool = False
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None


class ReviewState(BaseModel):
    review_id: str
    findings: List[ReviewedFinding]
    actions_applied: int = Field(ge=0)


class PreparedFeedback(BaseModel):
    """Final feedback a human reviewer approved, ready for STORY-006 to post to
    Basecamp. Saved once per review; after that the review is locked."""
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    reviewer_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    prepared_at: datetime
    status: Literal["ready_to_post"] = "ready_to_post"
    feedback_text: str = Field(min_length=1, max_length=MAX_PREPARED_FEEDBACK_CHARS)
    included_finding_ids: List[str] = Field(min_length=1)
    rejected_finding_ids: List[str]
    actions_applied: int = Field(ge=0)  # how much of the action log it reflects


class ReviewView(BaseModel):
    """What the reviewer page shows for one review."""
    review_id: str
    comment_id: int
    # From Basecamp when known (None otherwise). Personal data: page only.
    student_name: Optional[str] = None
    basecamp_url: Optional[str] = None
    stress_test_id: str
    rule_version: str
    # rule id -> readable check, e.g. "Dataset description is present".
    # Empty if the rule module could not be read (the page shows the codes).
    rule_names: Dict[str, str] = {}
    findings: List[ReviewedFinding]
    actions_applied: int = Field(ge=0)
    prepared: Optional[PreparedFeedback] = None
