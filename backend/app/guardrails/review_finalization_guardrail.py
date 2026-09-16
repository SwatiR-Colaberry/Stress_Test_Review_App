"""Enforces REQ-011: a review may only be finalized (marked Completed /
posted to Basecamp) once a genuine human reviewer has approved it. Raises
UnsafeFinalizationError otherwise.

Pure and synchronous by design: this is the gate every future finalize /
post-to-Basecamp code path must call, so it must not depend on the
database, Basecamp, or Claude being available.

See Master Project Specification Sec.22 (Status Model) and Sec.26 (MVP
Acceptance Criteria): "Completed must never mean AI finished" and "AI
never final-approves a submission."

Ported from the original Node.js implementation
(backend/src/services/guardrails/reviewFinalizationGuardrail.js); the
gate order and every reason code are preserved exactly.
"""
from typing import Set

from app.models import StressTestReview

AI_ACTOR_IDS: Set[str] = {"ai", "claude", "claude-ai", "system", "bot", "automation"}


class UnsafeFinalizationError(Exception):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.name = "UnsafeFinalizationError"
        self.error_class = "ContractViolation"
        self.reason_code = reason_code


def assert_safe_to_finalize(review: StressTestReview) -> dict:
    decision = review.reviewer_decision if review else None

    if decision is None:
        raise UnsafeFinalizationError(
            "NO_HUMAN_REVIEW",
            f"Review {review.review_id if review else None} has no reviewer decision recorded; cannot finalize.",
        )

    reviewer_id = decision.reviewer_id
    if not reviewer_id or not isinstance(reviewer_id, str) or reviewer_id.strip() == "":
        raise UnsafeFinalizationError(
            "MISSING_REVIEWER_IDENTITY",
            f"Review {review.review_id} decision has no reviewer identity; cannot finalize.",
        )

    normalized_reviewer_id = reviewer_id.strip().lower()
    normalized_ai_author_id = (review.ai_draft_author_id or "").strip().lower()
    if normalized_reviewer_id in AI_ACTOR_IDS or (
        normalized_ai_author_id and normalized_reviewer_id == normalized_ai_author_id
    ):
        raise UnsafeFinalizationError(
            "AI_CANNOT_APPROVE",
            f'Review {review.review_id} decision was recorded under an AI/system identity '
            f'("{reviewer_id}"); AI may never final-approve a submission.',
        )

    if decision.outcome != "approved":
        raise UnsafeFinalizationError(
            "NOT_APPROVED",
            f'Review {review.review_id} reviewer decision outcome is "{decision.outcome}", '
            f'not "approved"; cannot finalize.',
        )

    if not review.final_feedback_text or review.final_feedback_text.strip() == "":
        raise UnsafeFinalizationError(
            "EMPTY_FEEDBACK",
            f"Review {review.review_id} has no final feedback text; cannot finalize.",
        )

    return {"safe": True}
