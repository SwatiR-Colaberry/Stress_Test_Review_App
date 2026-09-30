"""Refuse feedback that must not be posted, before any Basecamp call (STORY-006
failure path "feedback data is malformed").

check_ready_to_post() returns the thread to post to, or raises PostingRefused
with a reason code. Nothing is sent to Basecamp for a refused review.
"""
from typing import FrozenSet, Optional

from app.guardrails.review_finalization_guardrail import AI_ACTOR_IDS
from app.human_review.models import MAX_PREPARED_FEEDBACK_CHARS, PreparedFeedback
from app.models import ReviewItem
from app.posting.models import PostingTarget


class PostingRefused(Exception):
    error_class = "ValidationError"

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def check_ready_to_post(
    item: ReviewItem, prepared: Optional[PreparedFeedback], allowed_project_ids: FrozenSet[int]
) -> PostingTarget:
    if prepared is None:
        raise PostingRefused("NO_PREPARED_FEEDBACK", "a reviewer has not prepared feedback for this review")
    if prepared.review_id != item.review_id:
        raise PostingRefused("FEEDBACK_REVIEW_MISMATCH", "the prepared feedback belongs to another review")
    # REQ-011, checked again at the last step: only a named human's feedback is posted.
    reviewer = (prepared.reviewer_id or "").strip().lower()
    if not reviewer or reviewer in AI_ACTOR_IDS:
        raise PostingRefused("REVIEWER_NOT_HUMAN", "feedback must be approved by a named human reviewer")
    if not prepared.feedback_text.strip():
        raise PostingRefused("EMPTY_FEEDBACK", "the prepared feedback is empty")
    if len(prepared.feedback_text) > MAX_PREPARED_FEEDBACK_CHARS:
        raise PostingRefused("FEEDBACK_TOO_LONG", f"feedback is over {MAX_PREPARED_FEEDBACK_CHARS} characters")
    if item.project_id is None:
        raise PostingRefused("NO_POSTING_TARGET", "the review does not say which Basecamp project it came from")
    if item.project_id not in allowed_project_ids:
        raise PostingRefused("PROJECT_NOT_ALLOWED", "the review's Basecamp project is not on the posting list")
    return PostingTarget(project_id=item.project_id, message_id=item.message_id)
