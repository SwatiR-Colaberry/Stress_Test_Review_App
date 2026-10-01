from datetime import datetime, timezone

import pytest

from app.review_queue.live_request import NoRequestFound, newest_request

STEP = "Stress Test 0 - Problem Definition"


def row(comment_id, when, body, email="student@example.com", name="Sam Student",
        url="https://3.basecamp.com/1/buckets/2/messages/3"):
    return {"BCP_ID": 77, "StepName": STEP, "MessageBoardURL": url, "MessageId": 900, "CommentId": comment_id,
            "CommentCreatedDate": when, "CreatorName": name, "CreatorEmail": email, "Comment": body}


def test_the_newest_student_request_and_the_thread_up_to_it_are_used():
    rows = [
        row(3, "2026-10-01 09:00:00", "<div>##Critique## second try, dataset link https://example.com/d</div>"),
        row(1, "2026-09-20 09:00:00", "<div>##Critique## first try</div>"),
        row(2, "2026-09-21 09:00:00", "<div>##FeedbackGiven## please fix the source</div>", email="rev@example.com"),
    ]
    live = newest_request(rows)
    assert live.comment.comment_id == 3 and live.comment.message_id == 900
    assert [c.comment_id for c in live.submission.comments] == [1, 2, 3]
    assert live.submission.comments[0].author_id == live.submission.comments[2].author_id != live.submission.comments[1].author_id
    assert live.comment.author_name == "Sam Student" and live.comment.app_url.startswith("https://3.basecamp.com/")
    assert live.comment.project_id == 2  # the bucket, for reading the comment's images
    assert live.step_name == STEP and live.later_comments == 0
    assert live.comment.created_at == datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def test_feedback_that_quotes_the_critique_marker_is_not_taken_for_the_request():
    rows = [row(1, "2026-10-01 09:00:00", "##Critique## please review"),
            row(2, "2026-10-01 10:00:00", "##FeedbackGiven## re your ##Critique##: add a link", email="rev@example.com")]
    live = newest_request(rows)
    assert live.comment.comment_id == 1 and live.later_comments == 1
    assert [c.comment_id for c in live.submission.comments] == [1]  # never the answer


def test_a_thread_without_a_request_is_refused():
    with pytest.raises(NoRequestFound):
        newest_request([row(1, "2026-10-01 09:00:00", "just a question")])
    with pytest.raises(NoRequestFound):
        newest_request([])


def test_a_non_basecamp_link_and_a_blank_name_are_dropped_not_fatal():
    live = newest_request([row(1, datetime(2026, 10, 1, 9), "##Critique##", name="  ", url="http://evil.example/x")])
    assert live.comment.app_url is None and live.comment.author_name is None and live.comment.project_id is None


def test_the_same_rows_give_the_same_request_every_time():
    rows = [row(1, "2026-10-01 09:00:00", "##Critique## a"), row(2, "2026-10-01 09:00:00", "##Critique## b")]
    assert newest_request(rows) == newest_request(list(reversed(rows)))
    assert newest_request(rows).comment.comment_id == 2  # same time: the higher comment id is newer
