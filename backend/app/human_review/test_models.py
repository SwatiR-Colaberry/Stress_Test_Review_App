import pytest
from pydantic import ValidationError

from app.human_review.models import MAX_REVIEWER_FINDING_CHARS, ReviewerAction
from app.models import AuditEvent


def _action(**fields):
    return ReviewerAction(action_id="a-1", **fields)


@pytest.mark.parametrize("kind", ["approve_finding", "reject_finding"])
def test_approve_and_reject_name_a_finding_and_carry_no_text(kind):
    action = _action(kind=kind, finding_id="ST0-001")
    assert action.finding_id == "ST0-001"
    assert action.text is None


def test_an_edit_keeps_the_reviewers_text_trimmed():
    action = _action(kind="edit_finding", finding_id="ST0-001", text="  Add the dataset link.  ")
    assert action.text == "Add the dataset link."


def test_an_added_finding_may_name_a_rule():
    action = _action(kind="add_finding", text="The problem statement is missing.", rule_id="ST0-002")
    assert action.rule_id == "ST0-002"


def test_a_long_st2_reviewer_finding_fits():
    # The median whole ST2 reply is 903 characters; one finding may be longer
    # than the AI's 400-character cap.
    action = _action(kind="edit_finding", finding_id="ST2-001", text="x" * MAX_REVIEWER_FINDING_CHARS)
    assert len(action.text) == MAX_REVIEWER_FINDING_CHARS


def test_text_over_the_limit_is_rejected():
    with pytest.raises(ValidationError):
        _action(kind="edit_finding", finding_id="ST2-001", text="x" * (MAX_REVIEWER_FINDING_CHARS + 1))


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "approve_finding"},  # no finding
        {"kind": "approve_finding", "finding_id": "ST0-001", "text": "why"},  # text on approve
        {"kind": "edit_finding", "finding_id": "ST0-001"},  # edit without text
        {"kind": "add_finding", "finding_id": "ST0-001", "text": "new"},  # add names an existing finding
        {"kind": "add_finding"},  # add without text
        {"kind": "reject_finding", "finding_id": "ST0-001", "rule_id": "ST0-001"},  # rule_id outside add
        {"kind": "edit_finding", "finding_id": "ST0-001", "text": "   "},  # blank edit
        {"kind": "delete_finding", "finding_id": "ST0-001"},  # unknown kind
        {"kind": "add_finding", "text": "new", "rule_id": "not-a-rule"},
        {"kind": "approve_finding", "finding_id": "ST0-001", "reviewer_id": "claude"},  # identity is not the body's
    ],
)
def test_malformed_actions_are_rejected(fields):
    with pytest.raises(ValidationError):
        _action(**fields)


def test_an_empty_action_id_is_rejected():
    with pytest.raises(ValidationError):
        ReviewerAction(action_id="", kind="approve_finding", finding_id="ST0-001")


def test_reviewer_actions_are_valid_audit_actions():
    event = AuditEvent(
        event_id="e-1", recorded_at="2026-09-29T12:00:00Z", action="reviewer_finding_edited",
        actor_id="reviewer-7", outcome="success", correlation_id="c-1", review_id="r-1", rule_id="ST0-001",
    )
    assert event.action == "reviewer_finding_edited"
