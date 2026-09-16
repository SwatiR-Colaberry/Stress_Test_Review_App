"""Pydantic models — the typed contract for the API (REQ-015) and the shared
shape guardrails and routers agree on. Formalizes what used to be JSDoc
@typedef comments (documentation only, not enforced) as real, validated types.
"""
from typing import List, Optional
from typing import Literal

from pydantic import BaseModel


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
