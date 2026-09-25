import pytest

from app.basecamp.critique_marker_detector import (
    classify_critique_marker,
    detect_review_markers,
    is_critique_marker,
    normalize_critique_marker,
)


def test_accepts_the_four_documented_spacing_variants():
    for variant in ["##Critique##", "## Critique##", "##Critique ##", "## Critique ##"]:
        assert is_critique_marker(variant) is True, f'expected "{variant}" to trigger'
        assert normalize_critique_marker(variant) == "##Critique##"


def test_accepts_reasonable_case_variants_of_the_same_spacing_forms():
    for variant in ["##critique##", "##CRITIQUE##", "## CrItIqUe ##"]:
        assert is_critique_marker(variant) is True, f'expected "{variant}" to trigger'


def test_detects_the_marker_embedded_inside_a_larger_comment():
    assert is_critique_marker("Done with V2, ready for review. ##Critique##") is True


def test_rejects_plain_critique_with_no_delimiters():
    assert is_critique_marker("Critique") is False


def test_rejects_a_single_hash_critique():
    assert is_critique_marker("#Critique") is False


def test_rejects_double_hash_review():
    assert is_critique_marker("##Review##") is False


def test_rejects_ordinary_prose_containing_the_word_critique():
    assert is_critique_marker("Can you give this a quick critique when you have time?") is False


def test_rejects_non_string_input_without_raising():
    assert is_critique_marker(None) is False
    assert is_critique_marker(42) is False


def test_idempotent_evaluating_the_same_comment_twice_yields_the_same_result():
    body = "## Critique ##"
    assert is_critique_marker(body) == is_critique_marker(body)
    assert normalize_critique_marker(body) == normalize_critique_marker(body)


def test_detect_review_markers_finds_each_marker_in_its_spacing_and_case_variants():
    assert detect_review_markers("## feedbackGiven ##") == ["FeedbackGiven"]
    assert detect_review_markers("Looks great ##APPROVED##") == ["Approved"]
    assert detect_review_markers("## Critique##") == ["Critique"]


def test_detect_review_markers_reports_every_marker_present():
    assert detect_review_markers("##FeedbackGiven## and ##Approved##") == ["FeedbackGiven", "Approved"]


def test_detect_review_markers_ignores_prose_review_markers_and_bad_input():
    assert detect_review_markers("Feedback given, approved in principle. ## Review ##") == []
    assert detect_review_markers(None) == []


# --- ##Please Critique## counts as a non-standard request (user decision, 2026-09-25) ---


@pytest.mark.parametrize("body", [
    "##Please Critique## my Dataset and Data Science Problem",
    "## please critique ##",
    "##PLEASE   CRITIQUE##",
])
def test_please_critique_is_a_nonstandard_request(body):
    assert classify_critique_marker(body) == "nonstandard"
    assert is_critique_marker(body) is False  # the standard check is unchanged


@pytest.mark.parametrize("body", ["##Critique##", "Please    ##Critique##", "## Critique ##"])
def test_the_taught_marker_is_standard(body):
    assert classify_critique_marker(body) == "standard"


def test_a_comment_with_both_markers_is_standard():
    assert classify_critique_marker("##Please Critique## ... ##Critique##") == "standard"


@pytest.mark.parametrize("body", ["#Critique#", "please critique my work", "##Please Review##", "## Review ##", None, 42])
def test_other_forms_are_still_not_critique_requests(body):
    assert classify_critique_marker(body) is None
