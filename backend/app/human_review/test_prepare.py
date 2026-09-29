from datetime import datetime, timezone

import pytest

from app.human_review.models import MAX_REVIEWER_FINDING_CHARS, ReviewerAction
from app.human_review.prepare import build_prepared
from app.human_review.state import InvalidReviewerAction, build_state
from app.human_review.store import ReviewActionStore, ReviewStoreError
from app.human_review.test_store import DRAFT, _Clock, _finding

_NOW = datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc)


def _act(action_id, kind, **fields):
    return ReviewerAction(action_id=action_id, kind=kind, **fields)


def _reviewed(tmp_path, *actions, draft=DRAFT):
    store = ReviewActionStore(tmp_path, clock=_Clock())
    for action in actions:
        store.record("r-1", "reviewer-7", action, draft)
    return store


APPROVE_1 = _act("a1", "approve_finding", finding_id="ST0-001")
EDIT_2 = _act("a2", "edit_finding", finding_id="ST0-002", text="Reviewer words.")
REJECT_2 = _act("a2", "reject_finding", finding_id="ST0-002")


def test_approved_findings_become_the_feedback_ready_to_post(tmp_path):
    store = _reviewed(tmp_path, APPROVE_1, EDIT_2)
    prepared = store.prepare("r-1", "reviewer-7", DRAFT)
    assert prepared.status == "ready_to_post"
    assert prepared.feedback_text == "1. AI suggestion.\n\n2. Reviewer words."
    assert prepared.included_finding_ids == ["ST0-001", "ST0-002"]
    assert prepared.reviewer_id == "reviewer-7"
    assert ReviewActionStore(tmp_path).prepared("r-1") == prepared  # saved to disk


def test_rejected_findings_are_left_out(tmp_path):
    prepared = _reviewed(tmp_path, APPROVE_1, REJECT_2).prepare("r-1", "reviewer-7", DRAFT)
    assert prepared.feedback_text == "1. AI suggestion."
    assert prepared.rejected_finding_ids == ["ST0-002"]


def test_a_pending_finding_blocks_preparation(tmp_path):
    store = _reviewed(tmp_path, APPROVE_1)
    with pytest.raises(InvalidReviewerAction) as err:
        store.prepare("r-1", "reviewer-7", DRAFT)
    assert err.value.reason_code == "UNDECIDED_FINDINGS"
    assert store.prepared("r-1") is None


def test_all_rejected_means_empty_feedback_and_is_refused(tmp_path):
    store = _reviewed(tmp_path, _act("a1", "reject_finding", finding_id="ST0-001"), REJECT_2)
    with pytest.raises(InvalidReviewerAction) as err:
        store.prepare("r-1", "reviewer-7", DRAFT)
    assert err.value.reason_code == "EMPTY_FEEDBACK"


def test_a_submission_with_no_ai_findings_needs_a_reviewer_note(tmp_path):
    store = _reviewed(tmp_path, _act("a1", "add_finding", text="Well done: every rule passes."), draft=[])
    assert store.prepare("r-1", "reviewer-7", []).feedback_text == "1. Well done: every rule passes."


@pytest.mark.parametrize("reviewer_id", ["claude", "bot"])
def test_ai_cannot_prepare_feedback(tmp_path, reviewer_id):
    store = _reviewed(tmp_path, APPROVE_1, EDIT_2)
    with pytest.raises(InvalidReviewerAction) as err:
        store.prepare("r-1", reviewer_id, DRAFT)
    assert err.value.reason_code == "AI_CANNOT_REVIEW"
    assert store.prepared("r-1") is None


def test_the_guardrail_refuses_an_ai_approver_even_if_called_directly():
    state = build_state("r-1", [], [])
    state.findings.append(build_state("r-1", DRAFT, []).findings[0].model_copy(update={"decision": "approved"}))
    with pytest.raises(InvalidReviewerAction) as err:
        build_prepared(state, "claude", _NOW)
    assert err.value.reason_code == "AI_CANNOT_APPROVE"


def test_long_st2_feedback_fits_but_over_the_limit_is_refused(tmp_path):
    draft = [_finding(f"ST2-00{n}") for n in range(1, 7)]
    edits = [_act(f"a{n}", "edit_finding", finding_id=f"ST2-00{n}", text="x" * MAX_REVIEWER_FINDING_CHARS)
             for n in range(1, 7)]
    store = _reviewed(tmp_path, *edits[:4], *[_act(f"r{n}", "reject_finding", finding_id=f"ST2-00{n}")
                                             for n in (5, 6)], draft=draft)
    assert len(store.prepare("r-1", "reviewer-7", draft).feedback_text) > 8000  # four long findings fit

    store = _reviewed(tmp_path / "over", *edits, draft=draft)  # six: over 10,000
    with pytest.raises(InvalidReviewerAction) as err:
        store.prepare("r-1", "reviewer-7", draft)
    assert err.value.reason_code == "FEEDBACK_TOO_LONG"


def test_preparing_twice_returns_the_saved_feedback(tmp_path):
    store = _reviewed(tmp_path, APPROVE_1, EDIT_2)
    first = store.prepare("r-1", "reviewer-7", DRAFT)
    assert store.prepare("r-1", "reviewer-7", DRAFT) == first
    assert len((tmp_path / "prepared.jsonl").read_text().splitlines()) == 1


def test_a_prepared_review_is_locked_but_a_replay_still_answers(tmp_path):
    store = _reviewed(tmp_path, APPROVE_1, EDIT_2)
    store.prepare("r-1", "reviewer-7", DRAFT)
    with pytest.raises(InvalidReviewerAction) as err:
        store.record("r-1", "reviewer-7", _act("a3", "reject_finding", finding_id="ST0-001"), DRAFT)
    assert err.value.reason_code == "REVIEW_LOCKED"
    store.record("r-1", "reviewer-7", APPROVE_1, DRAFT)  # a retried earlier click is not an error


def test_a_failed_save_raises_and_nothing_is_prepared(tmp_path):
    store = _reviewed(tmp_path, APPROVE_1, EDIT_2)
    (tmp_path / "prepared.jsonl").mkdir()
    with pytest.raises(ReviewStoreError):
        store.prepare("r-1", "reviewer-7", DRAFT)
