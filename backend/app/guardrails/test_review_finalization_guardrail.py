import pytest

from app.guardrails.review_finalization_guardrail import (
    UnsafeFinalizationError,
    assert_safe_to_finalize,
)
from app.models import ReviewerDecision, StressTestReview


def make_review(**overrides):
    defaults = dict(
        review_id="rev-1",
        final_feedback_text="Solid submission, approved.",
        ai_draft_author_id="claude-ai",
        reviewer_decision=ReviewerDecision(
            reviewer_id="jane.reviewer",
            outcome="approved",
            decided_at="2026-09-16T00:00:00Z",
        ),
    )
    defaults.update(overrides)
    return StressTestReview(**defaults)


def test_happy_path_genuine_human_approval_is_safe_to_finalize():
    assert assert_safe_to_finalize(make_review()) == {"safe": True}


def test_rejects_when_no_reviewer_decision_exists_at_all():
    review = make_review(reviewer_decision=None)
    with pytest.raises(UnsafeFinalizationError) as exc_info:
        assert_safe_to_finalize(review)
    assert exc_info.value.reason_code == "NO_HUMAN_REVIEW"


def test_rejects_a_decision_left_pending():
    review = make_review(reviewer_decision=ReviewerDecision(reviewer_id="jane.reviewer", outcome="pending"))
    with pytest.raises(UnsafeFinalizationError) as exc_info:
        assert_safe_to_finalize(review)
    assert exc_info.value.reason_code == "NOT_APPROVED"


def test_rejects_a_decision_the_reviewer_explicitly_rejected():
    review = make_review(reviewer_decision=ReviewerDecision(reviewer_id="jane.reviewer", outcome="rejected"))
    with pytest.raises(UnsafeFinalizationError) as exc_info:
        assert_safe_to_finalize(review)
    assert exc_info.value.reason_code == "NOT_APPROVED"


def test_rejects_when_the_ai_system_actor_is_recorded_as_the_approver():
    review = make_review(reviewer_decision=ReviewerDecision(reviewer_id="claude-ai", outcome="approved"))
    with pytest.raises(UnsafeFinalizationError) as exc_info:
        assert_safe_to_finalize(review)
    assert exc_info.value.reason_code == "AI_CANNOT_APPROVE"


def test_rejects_when_reviewer_id_matches_the_reviews_own_ai_draft_author_id():
    review = make_review(
        ai_draft_author_id="reviewer-bot-42",
        reviewer_decision=ReviewerDecision(reviewer_id="Reviewer-Bot-42", outcome="approved"),
    )
    with pytest.raises(UnsafeFinalizationError) as exc_info:
        assert_safe_to_finalize(review)
    assert exc_info.value.reason_code == "AI_CANNOT_APPROVE"


def test_rejects_when_reviewer_identity_is_blank():
    review = make_review(reviewer_decision=ReviewerDecision(reviewer_id="   ", outcome="approved"))
    with pytest.raises(UnsafeFinalizationError) as exc_info:
        assert_safe_to_finalize(review)
    assert exc_info.value.reason_code == "MISSING_REVIEWER_IDENTITY"


def test_rejects_empty_final_feedback_text_even_when_properly_approved():
    review = make_review(final_feedback_text="   ")
    with pytest.raises(UnsafeFinalizationError) as exc_info:
        assert_safe_to_finalize(review)
    assert exc_info.value.reason_code == "EMPTY_FEEDBACK"


def test_idempotent_evaluating_the_same_review_twice_yields_the_same_result():
    review = make_review()
    assert assert_safe_to_finalize(review) == assert_safe_to_finalize(review)
