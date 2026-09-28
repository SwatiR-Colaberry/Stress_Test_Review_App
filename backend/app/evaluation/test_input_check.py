from datetime import datetime, timezone

import pytest

from app.evaluation.input_check import (
    MAX_SUBMISSION_CHARS,
    SubmissionIncompleteError,
    prepare_evaluation_input,
)
from app.models import Submission, SubmissionComment, SubmissionLink
from app.rules.loader import MODULES_DIR, RuleLoadResult
from app.rules.module import RuleModule

_NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
_MODULE = RuleModule.model_validate_json((MODULES_DIR / "ST0" / "v1.json").read_text())
_LOADED = RuleLoadResult(outcome="loaded", stress_test_id="ST0", rule_version="v1", module=_MODULE)


def _submission(html="<div>Dataset: retail sales ##Critique##</div>"):
    comment = SubmissionComment(
        comment_id=2002, created_at=_NOW, content_html=html,
        links=[SubmissionLink(url="https://example.com/data", text="data")],
    )
    return Submission(
        message_id=500, title="Stress Test 0 - Dataset & DS Problem", created_at=_NOW,
        content_html="<div>Instructions</div>", comments=[comment],
    )


def test_a_complete_submission_becomes_an_evaluation_input():
    checked = prepare_evaluation_input(_submission(), 2002, _LOADED)
    assert (checked.comment_id, checked.message_id) == (2002, 500)
    assert checked.module.stress_test_id == "ST0"


def test_links_and_attachments_are_read_from_the_comment_html():
    html = (
        '<div>Source: <a href="https://www.kaggle.com/datasets/x">Kaggle</a></div>'
        '<bc-attachment content-type="text/csv" filename="sales.csv"></bc-attachment>'
    )
    checked = prepare_evaluation_input(_submission(html), 2002, _LOADED)  # built without links/attachments
    assert [link.url for link in checked.links] == ["https://www.kaggle.com/datasets/x"]
    assert [a.filename for a in checked.attachments] == ["sales.csv"]


def test_the_comment_is_sent_as_plain_text_with_the_highlight_kept():
    html = '<div>Problem 2</div><div><span style="background-color: rgb(250, 247, 133)">Problem 3</span></div>'
    text = prepare_evaluation_input(_submission(html), 2002, _LOADED).content_text
    assert text == "Problem 2\n\n[SELECTED]Problem 3[/SELECTED]"


def _reason(submission, comment_id, rules):
    with pytest.raises(SubmissionIncompleteError) as caught:
        prepare_evaluation_input(submission, comment_id, rules)
    return caught.value.reason_code


def test_rules_in_manual_resolution_are_rejected():
    manual = RuleLoadResult(outcome="manual_resolution", reason_code="NO_RULE_MODULE")
    assert _reason(_submission(), 2002, manual) == "RULES_NOT_LOADED"


def test_a_comment_missing_from_the_submission_is_rejected():
    assert _reason(_submission(), 9999, _LOADED) == "COMMENT_NOT_FOUND"


@pytest.mark.parametrize(
    "html",
    [
        "", "   ", "<div></div>", "<div> <br> </div>", "<p>\n</p>",
        '<bc-attachment content-type="image/png" filename="all-of-it.png"></bc-attachment>',
    ],
)
def test_an_empty_comment_is_rejected(html):
    assert _reason(_submission(html), 2002, _LOADED) == "SUBMISSION_EMPTY"


def test_an_oversized_comment_is_rejected_not_truncated():
    html = "<div>" + "x" * MAX_SUBMISSION_CHARS + "</div>"
    assert _reason(_submission(html), 2002, _LOADED) == "SUBMISSION_TOO_LARGE"


def test_a_comment_exactly_at_the_limit_is_accepted():
    html = "<p>" + "x" * (MAX_SUBMISSION_CHARS - 7) + "</p>"
    assert len(html) == MAX_SUBMISSION_CHARS
    assert prepare_evaluation_input(_submission(html), 2002, _LOADED).comment_id == 2002


def test_checking_twice_gives_the_same_result():
    first = prepare_evaluation_input(_submission(), 2002, _LOADED)
    assert prepare_evaluation_input(_submission(), 2002, _LOADED) == first


@pytest.mark.parametrize(
    "html",
    ["<div>Re your ##Critique##: add the source link. ##FeedbackGiven##</div>", "<div>##Critique## ok ##Approved##</div>"],
)
def test_a_reviewer_comment_is_not_evaluated(html):
    assert _reason(_submission(html), 2002, _LOADED) == "NOT_A_SUBMISSION"
