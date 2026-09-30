from datetime import datetime, timezone

import pytest

from app.human_review.models import MAX_PREPARED_FEEDBACK_CHARS, PreparedFeedback
from app.models import ReviewItem
from app.posting.checks import PostingRefused, check_ready_to_post
from app.posting.models import PostingTarget

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
ALLOWED = frozenset({111})


def item(**overrides):
    fields = dict(review_id="review-1", comment_id=9001, message_id=5001, created_at=NOW, project_id=111)
    fields.update(overrides)
    return ReviewItem(**fields)


def prepared(**overrides):
    fields = dict(review_id="review-1", reviewer_id="swati", prepared_at=NOW, feedback_text="1. Add the link.",
                  included_finding_ids=["ST0-002"], rejected_finding_ids=[], actions_applied=1)
    fields.update(overrides)
    return PreparedFeedback.model_construct(**fields)  # bypass validation: tests stored/tampered data


def test_ready_feedback_returns_the_thread_to_post_to():
    target = check_ready_to_post(item(), prepared(), ALLOWED)
    assert target == PostingTarget(project_id=111, message_id=5001)
    assert target.comments_path() == "/buckets/111/recordings/5001/comments.json"


@pytest.mark.parametrize("review, feedback, reason", [
    (item(), None, "NO_PREPARED_FEEDBACK"),
    (item(), prepared(review_id="review-2"), "FEEDBACK_REVIEW_MISMATCH"),
    (item(), prepared(reviewer_id="Claude"), "REVIEWER_NOT_HUMAN"),
    (item(), prepared(reviewer_id="  "), "REVIEWER_NOT_HUMAN"),
    (item(), prepared(feedback_text="  \n "), "EMPTY_FEEDBACK"),
    (item(), prepared(feedback_text="x" * (MAX_PREPARED_FEEDBACK_CHARS + 1)), "FEEDBACK_TOO_LONG"),
    (item(project_id=None), prepared(), "NO_POSTING_TARGET"),
    (item(project_id=222), prepared(), "PROJECT_NOT_ALLOWED"),
])
def test_malformed_feedback_is_refused_with_a_reason_code(review, feedback, reason):
    with pytest.raises(PostingRefused) as caught:
        check_ready_to_post(review, feedback, ALLOWED)
    assert caught.value.reason_code == reason


def test_nothing_is_allowed_when_the_posting_list_is_empty():
    with pytest.raises(PostingRefused) as caught:
        check_ready_to_post(item(), prepared(), frozenset())
    assert caught.value.reason_code == "PROJECT_NOT_ALLOWED"


def test_feedback_at_exactly_the_limit_is_accepted():
    check_ready_to_post(item(), prepared(feedback_text="x" * MAX_PREPARED_FEEDBACK_CHARS), ALLOWED)
