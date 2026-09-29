from datetime import datetime, timedelta, timezone

import pytest

from app.human_review.models import RecordedAction, ReviewerAction
from app.human_review.state import InvalidReviewerAction, build_state
from app.human_review.store import ReviewActionStore, ReviewStoreError
from app.models import DraftFinding

_T0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _finding(rule_id, feedback="AI suggestion."):
    return DraftFinding(rule_id=rule_id, status="FAIL", severity="Required Fix", evidence="e",
                        reason="r", suggested_feedback=feedback, confidence=0.9)


DRAFT = [_finding("ST0-001"), _finding("ST0-002")]


class _Clock:
    def __init__(self):
        self.now = _T0

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now


def _store(tmp_path):
    return ReviewActionStore(tmp_path, clock=_Clock())


def _act(action_id, kind, **fields):
    return ReviewerAction(action_id=action_id, kind=kind, **fields)


def _by_id(state):
    return {f.finding_id: f for f in state.findings}


def test_with_no_actions_every_ai_finding_is_pending_with_its_suggestion(tmp_path):
    state = _store(tmp_path).state("r-1", DRAFT)
    assert [(f.finding_id, f.decision, f.feedback_text) for f in state.findings] == [
        ("ST0-001", "pending", "AI suggestion."), ("ST0-002", "pending", "AI suggestion.")]


def test_approve_edit_reject_and_add_are_saved_with_reviewer_and_time(tmp_path):
    store = _store(tmp_path)
    store.record("r-1", "reviewer-7", _act("a1", "approve_finding", finding_id="ST0-001"), DRAFT)
    store.record("r-1", "reviewer-7", _act("a2", "edit_finding", finding_id="ST0-002", text="Reviewer words."), DRAFT)
    store.record("r-1", "reviewer-7", _act("a3", "add_finding", text="Also add a chart.", rule_id="ST0-003"), DRAFT)

    # A new store instance reads everything back from disk.
    found = _by_id(ReviewActionStore(tmp_path).state("r-1", DRAFT))
    assert found["ST0-001"].decision == "approved" and not found["ST0-001"].edited
    assert found["ST0-002"].feedback_text == "Reviewer words." and found["ST0-002"].edited
    assert found["ST0-002"].decision == "approved"
    assert found["ST0-002"].ai_draft.suggested_feedback == "AI suggestion."  # the AI draft is kept
    assert found["added-1"].source == "reviewer" and found["added-1"].feedback_text == "Also add a chart."
    assert found["ST0-001"].decided_by == "reviewer-7"
    assert found["ST0-001"].decided_at < found["ST0-002"].decided_at


def test_a_later_decision_replaces_an_earlier_one_and_history_keeps_both(tmp_path):
    store = _store(tmp_path)
    store.record("r-1", "reviewer-7", _act("a1", "reject_finding", finding_id="ST0-001"), DRAFT)
    state = store.record("r-1", "reviewer-7", _act("a2", "approve_finding", finding_id="ST0-001"), DRAFT)
    assert _by_id(state)["ST0-001"].decision == "approved"
    assert [r.action.kind for r in store.history("r-1")] == ["reject_finding", "approve_finding"]


def test_a_replayed_action_is_saved_once(tmp_path):
    store = _store(tmp_path)
    action = _act("a1", "add_finding", text="One added finding.")
    first = store.record("r-1", "reviewer-7", action, DRAFT)
    second = store.record("r-1", "reviewer-7", action, DRAFT)
    assert first == second
    assert len(store.history("r-1")) == 1
    assert [f.finding_id for f in second.findings].count("added-1") == 1


def test_an_action_id_reused_for_a_different_action_is_refused(tmp_path):
    store = _store(tmp_path)
    store.record("r-1", "reviewer-7", _act("a1", "approve_finding", finding_id="ST0-001"), DRAFT)
    with pytest.raises(InvalidReviewerAction) as err:
        store.record("r-1", "reviewer-7", _act("a1", "reject_finding", finding_id="ST0-001"), DRAFT)
    assert err.value.reason_code == "ACTION_ID_REUSED"


def test_an_unknown_finding_is_refused_and_nothing_is_saved(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(InvalidReviewerAction) as err:
        store.record("r-1", "reviewer-7", _act("a1", "approve_finding", finding_id="ST0-999"), DRAFT)
    assert err.value.reason_code == "UNKNOWN_FINDING"
    assert store.history("r-1") == []


@pytest.mark.parametrize("reviewer_id, reason", [
    ("claude", "AI_CANNOT_REVIEW"), (" System ", "AI_CANNOT_REVIEW"), ("  ", "MISSING_REVIEWER_IDENTITY")])
def test_ai_or_missing_identities_cannot_act(tmp_path, reviewer_id, reason):
    store = _store(tmp_path)
    with pytest.raises(InvalidReviewerAction) as err:
        store.record("r-1", reviewer_id, _act("a1", "approve_finding", finding_id="ST0-001"), DRAFT)
    assert err.value.reason_code == reason
    assert store.history("r-1") == []


def test_a_failed_write_raises_and_nothing_is_saved(tmp_path):
    (tmp_path / "actions.jsonl").mkdir()  # a directory where the file should be
    with pytest.raises(ReviewStoreError):
        _store(tmp_path).record("r-1", "reviewer-7", _act("a1", "approve_finding", finding_id="ST0-001"), DRAFT)


def test_a_corrupt_line_is_reported_not_skipped(tmp_path):
    (tmp_path / "actions.jsonl").write_text("not json\n")
    with pytest.raises(ReviewStoreError, match="line 1"):
        _store(tmp_path).state("r-1", DRAFT)


def test_reviews_do_not_see_each_others_actions(tmp_path):
    store = _store(tmp_path)
    store.record("r-1", "reviewer-7", _act("a1", "approve_finding", finding_id="ST0-001"), DRAFT)
    assert store.state("r-2", DRAFT).actions_applied == 0


def test_a_duplicated_log_line_is_applied_once():
    record = RecordedAction(review_id="r-1", reviewer_id="reviewer-7", recorded_at=_T0,
                            action=_act("a1", "add_finding", text="Once."))
    state = build_state("r-1", DRAFT, [record, record])
    assert state.actions_applied == 1
    assert len(state.findings) == 3
