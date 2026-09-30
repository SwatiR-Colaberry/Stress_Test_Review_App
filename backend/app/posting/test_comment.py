from app.posting.comment import (
    FEEDBACK_GIVEN_MARKER,
    build_comment_html,
    contains_feedback_id,
    feedback_id_for,
)
from app.basecamp.critique_marker_detector import detect_review_markers


def test_feedback_id_is_stable_per_review_and_differs_between_reviews():
    assert feedback_id_for("review-1") == feedback_id_for("review-1")
    assert feedback_id_for("review-1") != feedback_id_for("review-2")
    assert feedback_id_for("review-1").startswith("FB-") and len(feedback_id_for("review-1")) == 15


def test_comment_has_the_feedback_then_the_ref_then_the_marker():
    fid = feedback_id_for("review-1")
    body = build_comment_html("1. Add the dataset link.\n\n2. Pick one problem.", fid)
    assert body == (
        "<div>1. Add the dataset link.</div><div><br></div><div>2. Pick one problem.</div>"
        f"<div><br></div><div>Review ref: {fid}</div><div>{FEEDBACK_GIVEN_MARKER}</div>"
    )


def test_reviewer_text_is_escaped_so_it_cannot_inject_markup():
    body = build_comment_html('<script>alert(1)</script> & "quotes"', feedback_id_for("r"))
    assert "<script>" not in body
    assert "&lt;script&gt;" in body and "&amp;" in body


def test_the_posted_comment_carries_the_feedback_given_marker():
    body = build_comment_html("1. Good work.", feedback_id_for("r"))
    assert "FeedbackGiven" in detect_review_markers(body)


def test_ref_is_found_in_a_posted_comment_even_after_basecamp_reformats_it():
    fid = feedback_id_for("review-1")
    reformatted = f'<div class="trix">1. Good.</div><div>Review ref:&nbsp;{fid}</div>'.replace("&nbsp;", " ")
    assert contains_feedback_id(reformatted, fid)
    assert contains_feedback_id(build_comment_html("1. Good.", fid), fid)


def test_another_reviews_ref_or_an_empty_comment_does_not_match():
    fid = feedback_id_for("review-1")
    assert not contains_feedback_id(build_comment_html("1. Good.", feedback_id_for("review-2")), fid)
    assert not contains_feedback_id("", fid)
    assert not contains_feedback_id(None, fid)


def test_ref_is_found_when_basecamp_stores_the_space_as_nbsp():
    fid = feedback_id_for("review-1")
    assert contains_feedback_id(f"<div>Review ref:&nbsp;{fid}</div>", fid)
    assert contains_feedback_id(f"<div>Review&nbsp;ref:&nbsp;<strong>{fid}</strong></div>", fid)
