from datetime import datetime, timedelta, timezone

import pytest

from app.evaluation.thread import CommentNotInThreadError, read_thread
from app.models import Submission, SubmissionComment

_START = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
STUDENT, REVIEWER, OTHER_STUDENT = 11, 22, 33


def _thread(*comments, message_author=REVIEWER, message_html="<div>Stress Test 0 instructions</div>"):
    """comments: (comment_id, author_id, html) in posting order."""
    return Submission(
        message_id=500, title="Stress Test 0 - Dataset & DS Problem", author_id=message_author,
        created_at=_START, content_html=message_html,
        comments=[
            SubmissionComment(comment_id=cid, author_id=author, content_html=html,
                              created_at=_START + timedelta(hours=n + 1))
            for n, (cid, author, html) in enumerate(comments)
        ],
    )


def _ids(context):
    return [part.comment_id for part in context.parts]


def test_a_first_submission_is_version_1_with_no_previous_feedback():
    context = read_thread(_thread((1, STUDENT, "V1 ##Critique##")), 1)
    assert (context.version, _ids(context), context.previous_feedback) == (1, [1], None)
    assert not context.is_split


def test_a_resubmission_after_feedback_gets_that_feedback():
    thread = _thread(
        (1, STUDENT, "V1 ##Critique##"),
        (2, REVIEWER, "<div>Please add the source link. ##FeedbackGiven##</div>"),
        (3, STUDENT, "V2 with the link ##Critique##"),
    )
    context = read_thread(thread, 3)
    assert (context.version, _ids(context)) == (2, [3])
    assert context.previous_feedback.comment_id == 2
    assert context.previous_feedback.text == "Please add the source link. ##FeedbackGiven##"


def test_several_rounds_count_up_and_use_the_latest_feedback():
    # the user's cycle: Critique -> FeedbackGiven -> Critique -> FeedbackGiven -> Critique
    thread = _thread(
        (1, STUDENT, "V1 ##Critique##"), (2, REVIEWER, "Fix A ##FeedbackGiven##"),
        (3, STUDENT, "V2 ##Critique##"), (4, REVIEWER, "Fix B ##FeedbackGiven##"),
        (5, STUDENT, "V3 ##Critique##"),
    )
    assert (read_thread(thread, 5).version, read_thread(thread, 5).previous_feedback.comment_id) == (3, 4)
    assert (read_thread(thread, 3).version, read_thread(thread, 3).previous_feedback.comment_id) == (2, 2)
    assert read_thread(thread, 1).version == 1


def test_a_submission_split_over_comments_since_the_last_feedback_is_one_submission():
    thread = _thread(
        (1, STUDENT, "V1 ##Critique##"), (2, REVIEWER, "Fix A ##FeedbackGiven##"),
        (3, STUDENT, "Dataset part (no marker)"),
        (4, STUDENT, "Problems part ##Critique##"),
    )
    context = read_thread(thread, 4)
    assert _ids(context) == [3, 4]  # oldest first, the reviewed comment last
    assert context.is_split and context.previous_feedback.comment_id == 2


def test_other_peoples_comments_are_not_parts_of_the_submission():
    thread = _thread(
        (1, STUDENT, "Part one ##Critique##"),
        (2, REVIEWER, "Looking at this tomorrow."),  # unmarked reviewer chat
        (3, OTHER_STUDENT, "My own work ##Critique##"),  # someone else in the same thread
        (4, STUDENT, "Part two ##Critique##"),
    )
    assert _ids(read_thread(thread, 4)) == [1, 4]


def test_a_reviewer_comment_quoting_the_critique_marker_counts_as_feedback():
    thread = _thread(
        (1, STUDENT, "V1 ##Critique##"),
        (2, REVIEWER, "About your ##Critique##: add the link. ##FeedbackGiven##"),
        (3, STUDENT, "V2 ##Critique##"),
    )
    context = read_thread(thread, 3)
    assert (context.version, _ids(context), context.previous_feedback.comment_id) == (2, [3], 2)


def test_approved_also_ends_a_round():
    thread = _thread((1, STUDENT, "V1 ##Critique##"), (2, REVIEWER, "##Approved##"), (3, STUDENT, "Extra ##Critique##"))
    assert read_thread(thread, 3).version == 2


def test_the_students_own_message_is_part_of_a_first_submission():
    thread = _thread((1, STUDENT, "Rest of it ##Critique##"), message_author=STUDENT, message_html="<div>My dataset</div>")
    context = read_thread(thread, 1)
    assert _ids(context) == [None, 1]
    assert context.parts[0].content_html == "<div>My dataset</div>"


def test_the_message_is_not_a_part_when_someone_else_wrote_it():
    assert _ids(read_thread(_thread((1, STUDENT, "V1 ##Critique##")), 1)) == [1]


def test_without_author_ids_only_marked_comments_count_as_the_students():
    thread = _thread((1, None, "chat, no marker"), (2, None, "Part one ##Critique##"), (3, None, "Part two ##Critique##"))
    assert _ids(read_thread(thread, 3)) == [2, 3]


def test_comments_are_read_in_date_order_whatever_order_they_arrive_in():
    thread = _thread((1, STUDENT, "V1 ##Critique##"), (2, REVIEWER, "Fix ##FeedbackGiven##"), (3, STUDENT, "V2 ##Critique##"))
    thread.comments.reverse()
    assert read_thread(thread, 3).previous_feedback.comment_id == 2


def test_nothing_is_cut_from_long_parts():
    long_html = "<div>" + "x" * 50_000 + "</div>"
    context = read_thread(_thread((1, STUDENT, long_html + "##Critique##")), 1)
    assert len(context.parts[0].content_html) == len(long_html) + len("##Critique##")


def test_a_comment_outside_the_thread_is_an_error():
    with pytest.raises(CommentNotInThreadError):
        read_thread(_thread((1, STUDENT, "V1 ##Critique##")), 99)


def test_reading_twice_gives_the_same_context():
    thread = _thread((1, STUDENT, "V1 ##Critique##"), (2, REVIEWER, "Fix ##FeedbackGiven##"), (3, STUDENT, "V2 ##Critique##"))
    assert read_thread(thread, 3) == read_thread(thread, 3)
