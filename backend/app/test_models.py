from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import (
    AuditEvent,
    BasecampComment,
    ClaudeStageAnswer,
    DraftFinding,
    EvaluationResult,
    PrecheckResults,
    ReviewItem,
    TokenUsage,
)

_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def _comment(**overrides):
    fields = {"comment_id": 1001, "message_id": 500, "body": "##Critique##", "created_at": _NOW}
    fields.update(overrides)
    return fields


def test_a_well_formed_comment_parses():
    comment = BasecampComment(**_comment())
    assert comment.comment_id == 1001
    assert comment.message_id == 500


@pytest.mark.parametrize(
    "overrides",
    [
        {"comment_id": None},
        {"comment_id": 0},
        {"comment_id": -5},
        {"comment_id": "not-a-number"},
        {"comment_id": True},
        {"comment_id": "1001"},
        {"comment_id": 1001.0},
        {"message_id": None},
        {"body": None},
        {"created_at": "yesterday-ish"},
    ],
)
def test_malformed_comment_data_is_rejected(overrides):
    with pytest.raises(ValidationError):
        BasecampComment(**_comment(**overrides))


def test_a_comment_missing_its_id_entirely_is_rejected():
    fields = _comment()
    del fields["comment_id"]
    with pytest.raises(ValidationError):
        BasecampComment(**fields)


def test_a_new_review_item_defaults_to_pending():
    item = ReviewItem(review_id="r-1", comment_id=1001, message_id=500, created_at=_NOW)
    assert item.status == "Pending"


def test_a_review_item_rejects_a_status_outside_the_spec():
    with pytest.raises(ValidationError):
        ReviewItem(review_id="r-1", comment_id=1001, message_id=500, created_at=_NOW, status="Approved")


# --- STORY-004: draft findings and evaluation results ---


def _finding(**overrides):
    fields = {
        "rule_id": "ST0-001",
        "status": "FAIL",
        "severity": "Required Fix",
        "evidence": "No paragraph describes what the dataset contains.",
        "reason": "ST0-001 requires a brief dataset description.",
        "suggested_feedback": "Please add a brief description of the dataset.",
        "confidence": 0.9,
    }
    fields.update(overrides)
    return fields


def test_a_well_formed_draft_finding_parses():
    assert DraftFinding(**_finding()).rule_id == "ST0-001"
    assert DraftFinding(**_finding(status="ADVISORY")).status == "ADVISORY"


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "PASS"},  # passes are a list of ids, not findings
        {"status": "APPROVED"},
        {"status": "fail"},
        {"severity": "Critical"},
        {"rule_id": "ST0-1"},
        {"rule_id": "rule one"},
        {"confidence": 1.5},
        {"confidence": -0.1},
        {"evidence": ""},
        {"reason": ""},
        {"suggested_feedback": ""},
        {"evidence": "x" * 301},
        {"reason": "x" * 301},
        {"suggested_feedback": "x" * 401},
    ],
)
def test_malformed_draft_findings_are_rejected(overrides):
    with pytest.raises(ValidationError):
        DraftFinding(**_finding(**overrides))


def test_findings_at_the_length_caps_are_accepted():
    DraftFinding(**_finding(evidence="x" * 300, reason="x" * 300, suggested_feedback="x" * 400))


def test_a_draft_finding_with_an_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        DraftFinding(**_finding(approved=True))


def test_a_draft_finding_missing_confidence_is_rejected():
    fields = _finding()
    del fields["confidence"]
    with pytest.raises(ValidationError):
        DraftFinding(**fields)


def test_a_claude_stage_answer_parses_passes_and_findings():
    answer = ClaudeStageAnswer(passed_rule_ids=["ST0-002", "ST0-003"], findings=[_finding()])
    assert answer.passed_rule_ids == ["ST0-002", "ST0-003"]


@pytest.mark.parametrize(
    "fields",
    [
        {"passed_rule_ids": ["ST0-001"], "findings": [_finding()]},  # passed and failed
        {"passed_rule_ids": ["ST0-002", "ST0-002"], "findings": []},  # passed twice
        {"passed_rule_ids": ["bad"], "findings": []},
        {"passed_rule_ids": [], "findings": [], "approved": True},
    ],
)
def test_an_inconsistent_claude_stage_answer_is_rejected(fields):
    with pytest.raises(ValidationError):
        ClaudeStageAnswer(**fields)


_PRECHECKS = PrecheckResults(
    problem_count=9, selected_count=1, link_count=1, dataset_link_present=True,
    dataset_file_count=1, image_count=1,
)


def _result(**overrides):
    fields = {
        "comment_id": 1001,
        "message_id": 500,
        "stress_test_id": "ST0",
        "rule_version": "v1",
        "model": "claude-sonnet-5",
        "evaluated_at": _NOW,
        "correlation_id": "c-1",
        "stages_evaluated": [1],
        "passed_rule_ids": ["ST0-002"],
        "findings": [_finding()],
        "prechecks": _PRECHECKS,
        "usage": TokenUsage(input_tokens=100, output_tokens=20),
    }
    fields.update(overrides)
    return fields


def test_an_evaluation_result_parses_and_has_no_approval_field():
    result = EvaluationResult(**_result())
    assert result.findings[0].rule_id == "ST0-001"
    assert "status" not in EvaluationResult.model_fields
    assert not any("approv" in name for name in EvaluationResult.model_fields)


def test_an_all_pass_result_has_no_findings():
    assert EvaluationResult(**_result(findings=[], passed_rule_ids=["ST0-001"])).findings == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"stages_evaluated": []},
        {"comment_id": 0},
        {"stress_test_id": "ST10"},
        {"passed_rule_ids": ["ST0-001"]},  # also in findings
    ],
)
def test_an_invalid_evaluation_result_is_rejected(overrides):
    with pytest.raises(ValidationError):
        EvaluationResult(**_result(**overrides))


def test_token_usage_adds_and_totals():
    one = TokenUsage(input_tokens=10, cache_creation_input_tokens=5, cache_read_input_tokens=100, output_tokens=7)
    both = one + one
    assert both.cache_read_input_tokens == 200
    assert both.total == 244


@pytest.mark.parametrize(
    "action",
    [
        "evaluation_started", "evaluation_finding", "evaluation_completed", "evaluation_failed",
        "evaluation_already_done", "evaluation_manual_resolution",
    ],
)
def test_evaluation_audit_actions_carry_submission_and_rule_ids(action):
    event = AuditEvent(
        event_id="e-1", recorded_at=_NOW, action=action, actor_id="system", outcome="success",
        correlation_id="c-1", comment_id=1001, message_id=500, rule_id="ST0-001",
    )
    assert (event.comment_id, event.rule_id) == (1001, "ST0-001")
