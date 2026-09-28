"""evaluate_submission() with a scripted fake Claude: no network, no cost."""
from datetime import datetime, timezone
import pytest

from app.audit.trail import AuditTrail, AuditWriteError, InMemoryAuditTrail
from app.evaluation.claude_client import ClaudeUnavailableError, EvaluationTimeoutError, MalformedReplyError
from app.evaluation.config import EvaluationConfig
from app.evaluation.evaluate import EvaluationManualResolutionError, RuleCoverageError, evaluate_submission
from app.evaluation.fake import FAKE_USAGE, ScriptedEvaluator
from app.evaluation.input_check import SubmissionIncompleteError
from app.evaluation.store import (
    DailyTokenLimitExceededError,
    EvaluationInProgressError,
    EvaluationStoreError,
    ResultStore,
    UsageLedger,
    UsageRecord,
)
from app.models import ClaudeStageAnswer, Submission, SubmissionComment, TokenUsage
from app.rules.loader import MODULES_DIR, RuleLoadResult
from app.rules.module import RuleModule

_NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
_MODULE = RuleModule.model_validate_json((MODULES_DIR / "ST0" / "v1.json").read_text())
_RULES = RuleLoadResult(outcome="loaded", stress_test_id="ST0", rule_version="v1", module=_MODULE)
_STAGE_1 = ["ST0-001", "ST0-002", "ST0-003", "ST0-006", "ST0-007", "ST0-008"]
_STAGE_2 = ["ST0-004", "ST0-005"]
_CONFIG = EvaluationConfig(api_key="sk-ant-test-0000", max_tokens=1000, max_input_tokens=5000, daily_token_limit=100_000)
_USAGE = FAKE_USAGE


def _finding(rule_id, status="FAIL", severity="Needs Attention"):
    return {"rule_id": rule_id, "status": status, "severity": severity, "evidence": "e", "reason": "r",
            "suggested_feedback": "f", "confidence": 0.7}


def _answer(passed, findings=()):
    return ClaudeStageAnswer(passed_rule_ids=list(passed), findings=list(findings))


def _submission(html="<div>- Problem: churn\n- Solution: classify</div><div>##Critique##</div>"):
    return Submission(
        message_id=500, title="Stress Test 0 - Dataset & DS Problem", created_at=_NOW, content_html="<div>x</div>",
        comments=[SubmissionComment(comment_id=2002, created_at=_NOW, content_html=html)],
    )


@pytest.fixture
def env(tmp_path):
    audit = InMemoryAuditTrail()
    return {
        "store": ResultStore(tmp_path), "ledger": UsageLedger(tmp_path, daily_limit=_CONFIG.daily_token_limit),
        "audit": audit, "config": _CONFIG, "clock": lambda: _NOW,
    }


def _evaluate(claude, env, submission=None, rules=_RULES, comment_id=2002):
    return evaluate_submission(submission or _submission(), comment_id, rules, evaluator=claude, correlation_id="corr-1", **env)


def _actions(env):
    return [(e.action, e.rule_id, e.reason_code) for e in env["audit"].read_all()]


def test_a_valid_submission_returns_structured_draft_findings(env):
    claude = ScriptedEvaluator(_answer(_STAGE_1[1:], [_finding("ST0-001", "ADVISORY")]), _answer(_STAGE_2))
    result = _evaluate(claude, env)
    assert result.stages_evaluated == [1, 2]
    assert sorted(result.passed_rule_ids) == sorted(_STAGE_1[1:] + _STAGE_2)
    finding = result.findings[0]
    assert (finding.rule_id, finding.status) == ("ST0-001", "ADVISORY")
    assert finding.severity == "Required Fix"  # from the rule module, not from Claude's "Needs Attention"
    assert (result.comment_id, result.message_id, result.rule_version) == (2002, 500, "v1")
    assert result.usage.cache_read_input_tokens == 3000  # both stages summed
    assert len(claude.prompts) == 2


def test_a_stage_1_failure_stops_before_stage_2(env):
    claude = ScriptedEvaluator(_answer(_STAGE_1[1:], [_finding("ST0-001")]))
    result = _evaluate(claude, env)
    assert result.stages_evaluated == [1]
    assert len(claude.prompts) == 1  # Stage 2 was never sent
    assert not any(rule_id in claude.prompts[0].user.split("\n")[0] for rule_id in _STAGE_2)
    assert all(rule_id not in result.passed_rule_ids for rule_id in _STAGE_2)


def test_every_evaluated_rule_is_audited_with_submission_and_rule_id(env):
    _evaluate(ScriptedEvaluator(_answer(_STAGE_1[1:], [_finding("ST0-001")])), env)
    events = env["audit"].read_all()
    assert [e.action for e in events][0] == "evaluation_started"
    assert [e.action for e in events][-1] == "evaluation_completed"
    findings = [e for e in events if e.action == "evaluation_finding"]
    assert sorted(e.rule_id for e in findings) == sorted(_STAGE_1)
    assert {e.comment_id for e in events} == {2002} and {e.message_id for e in events} == {500}
    assert {e.rule_version for e in events} == {"v1"} and {e.correlation_id for e in events} == {"corr-1"}
    assert ("evaluation_finding", "ST0-001", "FAIL") in _actions(env)
    assert ("evaluation_finding", "ST0-002", "PASS") in _actions(env)


def test_the_same_version_is_never_sent_to_claude_twice(env):
    first = _evaluate(ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2)), env)
    again = ScriptedEvaluator()  # would fail if called: no scripted replies
    assert _evaluate(again, env) == first
    assert again.prompts == []
    assert _actions(env)[-1] == ("evaluation_already_done", None, None)


def test_a_run_in_progress_blocks_a_second_one(env):
    with env["store"].claim(2002, "v1"):
        with pytest.raises(EvaluationInProgressError):
            _evaluate(ScriptedEvaluator(), env)


def test_a_result_finished_by_another_run_while_waiting_is_reused(env, monkeypatch):
    first = _evaluate(ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2)), env)
    calls = iter([None, first])  # nothing stored at first look; stored by the time the claim is held
    monkeypatch.setattr(env["store"], "get", lambda *_: next(calls))
    claude = ScriptedEvaluator()
    assert _evaluate(claude, env) == first
    assert claude.prompts == []


def test_usage_of_every_call_reaches_the_ledger(env):
    _evaluate(ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2)), env)
    assert env["ledger"].used_on(_NOW.date()) == 2 * _USAGE.total


@pytest.mark.parametrize(
    "html, reason",
    [("<div> </div>", "SUBMISSION_EMPTY"), ('<bc-attachment content-type="image/png" filename="a.png"></bc-attachment>', "SUBMISSION_EMPTY")],
)
def test_an_invalid_submission_returns_an_error_without_calling_claude(env, html, reason):
    claude = ScriptedEvaluator()
    with pytest.raises(SubmissionIncompleteError) as caught:
        _evaluate(claude, env, submission=_submission(html))
    assert caught.value.reason_code == reason
    assert claude.prompts == []
    assert _actions(env)[-1] == ("evaluation_failed", None, reason)
    assert env["store"].get(2002, "v1") is None


def test_a_missing_comment_is_an_error(env):
    with pytest.raises(SubmissionIncompleteError, match="9999"):
        _evaluate(ScriptedEvaluator(), env, comment_id=9999)


def test_rules_in_manual_resolution_are_an_error(env):
    manual = RuleLoadResult(outcome="manual_resolution", reason_code="NO_RULE_MODULE")
    with pytest.raises(SubmissionIncompleteError):
        _evaluate(ScriptedEvaluator(), env, rules=manual)
    assert _actions(env) == [("evaluation_failed", None, "RULES_NOT_LOADED")]


def test_an_oversized_submission_goes_to_manual_resolution(env):
    claude = ScriptedEvaluator(input_tokens=_CONFIG.max_input_tokens + 1)
    with pytest.raises(EvaluationManualResolutionError) as caught:
        _evaluate(claude, env)
    assert caught.value.reason_code == "INPUT_TOO_LARGE"
    assert claude.prompts == []
    assert _actions(env)[-1] == ("evaluation_manual_resolution", None, "INPUT_TOO_LARGE")


def test_the_daily_token_limit_stops_the_call(env):
    used = _CONFIG.daily_token_limit - 2000 - _CONFIG.max_tokens + 1  # one token short of room for this call
    env["ledger"].record(UsageRecord(recorded_at=_NOW, comment_id=1, stage=1, model="m",
                                     usage=TokenUsage(input_tokens=used)))
    claude = ScriptedEvaluator()
    with pytest.raises(DailyTokenLimitExceededError):
        _evaluate(claude, env)
    assert claude.prompts == []
    assert _actions(env)[-1] == ("evaluation_failed", None, "DAILY_TOKEN_LIMIT")


@pytest.mark.parametrize(
    "error, reason",
    [
        (ClaudeUnavailableError("Claude API unreachable after 3 attempts"), "UpstreamUnavailable"),
        (EvaluationTimeoutError("Claude did not answer within 60 s"), "TimeoutError"),
    ],
)
def test_claude_failures_are_errors_and_can_be_retried_later(env, error, reason):
    with pytest.raises(type(error)):
        _evaluate(ScriptedEvaluator(error), env)
    assert _actions(env)[-1] == ("evaluation_failed", None, reason)
    assert env["store"].get(2002, "v1") is None
    result = _evaluate(ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2)), env)  # a later run may try again
    assert result.stages_evaluated == [1, 2]


def test_a_failure_in_stage_2_stores_nothing(env):
    with pytest.raises(ClaudeUnavailableError):
        _evaluate(ScriptedEvaluator(_answer(_STAGE_1), ClaudeUnavailableError("down")), env)
    assert env["store"].get(2002, "v1") is None
    assert env["ledger"].used_on(_NOW.date()) == _USAGE.total  # Stage 1 tokens were still spent


def test_a_malformed_reply_with_usage_is_still_counted(env):
    with pytest.raises(MalformedReplyError):
        _evaluate(ScriptedEvaluator(MalformedReplyError("cut off", usage=_USAGE, request_id="req_x")), env)
    assert env["ledger"].used_on(_NOW.date()) == _USAGE.total


@pytest.mark.parametrize(
    "answer",
    [
        _answer(_STAGE_1[1:]),  # ST0-001 missing
        _answer(_STAGE_1 + ["ST0-004"]),  # a Stage 2 rule in Stage 1
        _answer(_STAGE_1 + ["ST0-009"]),  # a rule that does not exist
        _answer(_STAGE_1[:-1] + ["ST1-001"]),  # another Stress Test's rule
    ],
)
def test_an_answer_that_does_not_cover_exactly_the_stage_rules_is_rejected(env, answer):
    with pytest.raises(RuleCoverageError):
        _evaluate(ScriptedEvaluator(answer), env)
    assert _actions(env)[-1] == ("evaluation_failed", None, "RULE_COVERAGE")
    assert env["store"].get(2002, "v1") is None


class _FailingOn(AuditTrail):
    def __init__(self, action):
        self.action, self.inner = action, InMemoryAuditTrail()

    def record(self, event):
        if event.action == self.action:
            raise AuditWriteError("disk full")
        self.inner.record(event)

    def read_all(self):
        return self.inner.read_all()


def test_nothing_is_sent_if_the_start_cannot_be_audited(env):
    env["audit"] = _FailingOn("evaluation_started")
    claude = ScriptedEvaluator()
    with pytest.raises(AuditWriteError):
        _evaluate(claude, env)
    assert claude.prompts == []


def test_an_audit_failure_after_storing_does_not_cost_a_second_call(env):
    env["audit"] = _FailingOn("evaluation_completed")
    with pytest.raises(AuditWriteError):
        _evaluate(ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2)), env)
    stored = env["store"].get(2002, "v1")
    assert stored is not None
    env["audit"] = InMemoryAuditTrail()
    assert _evaluate(ScriptedEvaluator(), env) == stored


def test_a_failure_that_cannot_be_audited_still_surfaces_the_original_error(env):
    env["audit"] = _FailingOn("evaluation_failed")
    with pytest.raises(ClaudeUnavailableError):
        _evaluate(ScriptedEvaluator(ClaudeUnavailableError("down")), env)


def test_the_result_never_carries_an_approval(env):
    result = _evaluate(ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2)), env)
    assert result.findings == []  # every rule passed ...
    assert not any("approv" in name or name == "status" for name in type(result).model_fields)  # ... still a draft


def test_a_result_that_cannot_be_stored_is_audited_as_failed(env, monkeypatch):
    def broken_put(result):
        raise EvaluationStoreError("Could not write results.jsonl: OSError")

    monkeypatch.setattr(env["store"], "put", broken_put)
    with pytest.raises(EvaluationStoreError):
        _evaluate(ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2)), env)
    assert _actions(env)[-1] == ("evaluation_failed", None, "EvaluationStoreError")
    assert env["ledger"].used_on(_NOW.date()) == 2 * _USAGE.total  # the spent tokens are still counted
