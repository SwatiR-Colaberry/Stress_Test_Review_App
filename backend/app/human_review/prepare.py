"""Turn a fully reviewed state into the feedback prepared for Basecamp
(STORY-005). Pure: no files; the store saves the result.

Refused (InvalidReviewerAction, nothing prepared) when:
  UNDECIDED_FINDINGS   a finding is still pending: every AI finding needs a
                       human decision before anything reaches the student
  FEEDBACK_TOO_LONG    the text is over MAX_PREPARED_FEEDBACK_CHARS
  EMPTY_FEEDBACK / AI_CANNOT_APPROVE / ...  the REQ-011 finalization guardrail
                       said no (same reason codes as /reviews/finalize-check).
                       No approved finding means empty feedback: a reviewer
                       with nothing to criticise adds a finding with their note.

Format: approved findings numbered in review order (AI findings in draft
order, then reviewer-added ones), one paragraph each, reviewer wording where
edited. Rejected findings are left out.
"""
from datetime import datetime

from app.guardrails.review_finalization_guardrail import UnsafeFinalizationError, assert_safe_to_finalize
from app.human_review.models import MAX_PREPARED_FEEDBACK_CHARS, PreparedFeedback, ReviewState
from app.human_review.state import InvalidReviewerAction
from app.models import ReviewerDecision, StressTestReview

# The author recorded on every AI draft; the guardrail refuses it as approver.
AI_DRAFT_AUTHOR_ID = "claude"


def compose_feedback(state: ReviewState) -> str:
    approved = [f for f in state.findings if f.decision == "approved"]
    return "\n\n".join(f"{n}. {f.feedback_text}" for n, f in enumerate(approved, start=1))


def build_prepared(state: ReviewState, reviewer_id: str, now: datetime) -> PreparedFeedback:
    pending = [f.finding_id for f in state.findings if f.decision == "pending"]
    if pending:
        raise InvalidReviewerAction(
            "UNDECIDED_FINDINGS", f"review {state.review_id} still has undecided findings: {pending}"
        )
    text = compose_feedback(state)
    if len(text) > MAX_PREPARED_FEEDBACK_CHARS:
        raise InvalidReviewerAction(
            "FEEDBACK_TOO_LONG", f"feedback is {len(text)} characters (limit {MAX_PREPARED_FEEDBACK_CHARS})"
        )
    review = StressTestReview(
        review_id=state.review_id, final_feedback_text=text, ai_draft_author_id=AI_DRAFT_AUTHOR_ID,
        reviewer_decision=ReviewerDecision(reviewer_id=reviewer_id, outcome="approved", decided_at=now.isoformat()),
    )
    try:
        assert_safe_to_finalize(review)
    except UnsafeFinalizationError as exc:
        raise InvalidReviewerAction(exc.reason_code, str(exc)) from exc
    return PreparedFeedback(
        review_id=state.review_id, reviewer_id=reviewer_id, prepared_at=now, feedback_text=text,
        included_finding_ids=[f.finding_id for f in state.findings if f.decision == "approved"],
        rejected_finding_ids=[f.finding_id for f in state.findings if f.decision == "rejected"],
        actions_applied=state.actions_applied,
    )
