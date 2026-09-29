"""Evaluate one submission with Claude (STORY-004: REQ-005).

evaluate_submission() is the only entry point. In order:
 1. A result already stored for (comment_id, rule_version) is returned and
    Claude is NOT called again (evaluation_already_done).
 2. The key is claimed so no concurrent run evaluates it too, and
    evaluation_started is recorded before anything is sent.
 3. Input check + deterministic pre-checks; an incomplete submission raises
    SubmissionIncompleteError (the "invalid submission" error).
 4. For each blocking stage in order: count tokens (over the limit ->
    manual resolution), check the daily budget, call Claude, record usage,
    check the answer covers exactly that stage's rules, take severity from
    the rule module. If Stage 1 has a FAIL, Stage 2 is not evaluated.
 5. The result is stored, then one evaluation_finding per evaluated rule
    (submission id + rule id + PASS/FAIL/ADVISORY) and evaluation_completed.

Every failure records evaluation_failed (or evaluation_manual_resolution)
with a reason code and is re-raised; nothing is stored, so the submission can
be evaluated again later. The result is a draft: it has no approval field,
and nothing here changes a review's status (REQ-011).

Ordering: the result is stored BEFORE the finding/completed audit events.
If those writes fail, AuditWriteError is raised and a re-run returns the
stored result without paying for Claude twice. (Reversed, the trail could say
"completed" for a result that was never saved.) Known gap, as in STORY-011:
the store and the trail are not written in one transaction.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, List, Optional

from app.audit.trail import AuditTrail, AuditWriteError
from app.evaluation.claude_client import ClaudeReply, EvaluationError, Evaluator, MalformedReplyError
from app.evaluation.config import EvaluationConfig
from app.evaluation.input_check import EvaluationInput, SubmissionIncompleteError, prepare_evaluation_input
from app.evaluation.prechecks import run_prechecks
from app.evaluation.prompt import build_prompt
from app.evaluation.store import (
    DailyTokenLimitExceededError,
    EvaluationStoreError,
    ResultStore,
    UsageLedger,
    UsageRecord,
)
from app.models import AuditEvent, DraftFinding, EvaluationResult, HistoryRetrieval, Submission, TokenUsage
from app.rules.loader import RuleLoadResult

logger = logging.getLogger("stress_test_review.evaluation")

# (stress_test_id, submission_text) -> similar past reviews (STORY-013,
# app.history.retrieval.retrieve_similar_cases with its index and model bound).
# It reports an outage in its result instead of raising, so the review goes on.
HistoryLookup = Callable[[str, str], HistoryRetrieval]


class EvaluationManualResolutionError(Exception):
    """The submission must be reviewed without AI (e.g. too many tokens)."""
    error_class = "ManualResolution"

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class RuleCoverageError(MalformedReplyError):
    """Claude's answer did not cover exactly the rules it was asked about."""


class _Recorder:
    """Writes audit events and JSON log lines for one evaluation."""

    def __init__(self, audit: AuditTrail, actor_id: str, correlation_id: str,
                 comment_id: int, message_id: int, rules: RuleLoadResult) -> None:
        self.audit, self.actor_id, self.correlation_id = audit, actor_id, correlation_id
        self.ids = {"comment_id": comment_id, "message_id": message_id,
                    "stress_test_id": rules.stress_test_id, "rule_version": rules.rule_version}

    def record(self, action: str, outcome: str, rule_id: Optional[str] = None,
               reason_code: Optional[str] = None) -> None:
        event = AuditEvent(
            event_id=str(uuid.uuid4()), recorded_at=datetime.now(timezone.utc), action=action,
            actor_id=self.actor_id, outcome=outcome, correlation_id=self.correlation_id,
            rule_id=rule_id, reason_code=reason_code, **self.ids,
        )
        try:
            self.audit.record(event)
        except AuditWriteError:
            self.log(logging.ERROR, "audit_write_failed", audit_action=action, error_class=AuditWriteError.error_class)
            raise
        self.log(logging.INFO if outcome == "success" else logging.WARNING, action,
                 rule_id=rule_id, reason_code=reason_code)

    def record_failure(self, action: str, reason_code: str) -> None:
        """Record a failure; if even that cannot be recorded, log it and let
        the caller re-raise the ORIGINAL error (it is the one to surface)."""
        try:
            self.record(action, "blocked" if action == "evaluation_manual_resolution" else "failure",
                        reason_code=reason_code)
        except AuditWriteError:
            pass  # already logged as audit_write_failed

    def log(self, level: int, event: str, **context: object) -> None:
        logger.log(level, json.dumps({
            "event": event, "service": "backend", "correlation_id": self.correlation_id,
            "context": {**self.ids, **{k: v for k, v in context.items() if v is not None}},
        }))


def _reason_code(error: Exception) -> str:
    if isinstance(error, RuleCoverageError):
        return "RULE_COVERAGE"
    if isinstance(error, (SubmissionIncompleteError, EvaluationManualResolutionError)):
        return error.reason_code
    if isinstance(error, DailyTokenLimitExceededError):
        return "DAILY_TOKEN_LIMIT"
    return getattr(error, "error_class", type(error).__name__)


def evaluate_submission(
    submission: Submission,
    comment_id: int,
    rules: RuleLoadResult,
    *,
    evaluator: Evaluator,
    store: ResultStore,
    ledger: UsageLedger,
    audit: AuditTrail,
    config: EvaluationConfig,
    actor_id: str = "system",
    correlation_id: Optional[str] = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    history: Optional[HistoryLookup] = None,
) -> EvaluationResult:
    recorder = _Recorder(audit, actor_id, correlation_id or str(uuid.uuid4()),
                         comment_id, submission.message_id, rules)
    if rules.outcome != "loaded" or rules.module is None:
        recorder.record_failure("evaluation_failed", "RULES_NOT_LOADED")
        raise SubmissionIncompleteError("RULES_NOT_LOADED", f"no rule module loaded (reason: {rules.reason_code})")

    version = rules.module.version
    stored = store.get(comment_id, version)
    if stored is not None:
        recorder.record("evaluation_already_done", "success")
        return stored

    with store.claim(comment_id, version):
        stored = store.get(comment_id, version)  # finished by another run while we waited
        if stored is not None:
            recorder.record("evaluation_already_done", "success")
            return stored
        recorder.record("evaluation_started", "success")
        try:
            result = store.put(_run(submission, comment_id, evaluator, ledger, config, recorder, clock, rules,
                                    history))
        except EvaluationManualResolutionError as error:
            recorder.record_failure("evaluation_manual_resolution", error.reason_code)
            raise
        except (SubmissionIncompleteError, DailyTokenLimitExceededError, EvaluationError, EvaluationStoreError) as error:
            recorder.record_failure("evaluation_failed", _reason_code(error))
            raise
        for rule_id in result.passed_rule_ids:
            recorder.record("evaluation_finding", "success", rule_id=rule_id, reason_code="PASS")
        for finding in result.findings:
            recorder.record("evaluation_finding", "success", rule_id=finding.rule_id, reason_code=finding.status)
        recorder.record("evaluation_completed", "success")
        return result


def _run(submission: Submission, comment_id: int, evaluator: Evaluator, ledger: UsageLedger,
         config: EvaluationConfig, recorder: _Recorder, clock: Callable[[], datetime],
         rules: RuleLoadResult, history: Optional[HistoryLookup] = None) -> EvaluationResult:
    checked = prepare_evaluation_input(submission, comment_id, rules)
    prechecks = run_prechecks(checked)
    past = _retrieve_history(history, checked, recorder)
    stages: List[int] = []
    passed: List[str] = []
    findings: List[DraftFinding] = []
    usage = TokenUsage()
    model = evaluator.model

    for stage in [s for s in checked.module.stages if s.blocking and s.rule_ids]:
        reply = _evaluate_stage(checked, stage.number, stage.rule_ids, prechecks, evaluator, ledger, config, clock,
                                past)
        stages.append(stage.number)
        passed += reply.answer.passed_rule_ids
        findings += [
            f.model_copy(update={"severity": checked.module.rule(f.rule_id).default_severity})
            for f in reply.answer.findings
        ]
        usage, model = usage + reply.usage, reply.model
        if any(f.status == "FAIL" for f in reply.answer.findings):
            break  # a failing blocking stage stops here (ST0: Stage 2 is not evaluated)

    return EvaluationResult(
        comment_id=checked.comment_id, message_id=checked.message_id,
        stress_test_id=checked.module.stress_test_id, rule_version=checked.module.version,
        model=model, evaluated_at=clock(), correlation_id=recorder.correlation_id,
        stages_evaluated=stages, passed_rule_ids=passed, findings=findings,
        prechecks=prechecks, usage=usage, history=past,
    )


def _retrieve_history(history: Optional[HistoryLookup], checked: EvaluationInput,
                      recorder: _Recorder) -> Optional[HistoryRetrieval]:
    """Once per submission (both stages see the same examples). An outage is
    in the result, not raised: the evaluation continues without examples."""
    if history is None:
        return None
    test = checked.module.stress_test_id
    try:
        past = history(test, checked.content_text)
    except Exception as error:  # noqa: BLE001 — optional examples must never stop a review (REQ-019)
        # The lookup reports outages in its result; reaching here is a bug in
        # it. Log the class (never the message: it may quote text) and go on.
        recorder.log(logging.ERROR, "history_lookup_failed", error_class=type(error).__name__)
        past = HistoryRetrieval(stress_test_id=test, status="unavailable", cases=[], error_class="HistoryLookupFailed",
                                message="Historical examples are unavailable (the lookup failed unexpectedly); "
                                        "this review continues without them.")
    recorder.record("history_retrieved", "failure" if past.status == "unavailable" else "success",
                    reason_code=past.error_class or past.status)
    return past


def _evaluate_stage(checked: EvaluationInput, stage_number: int, rule_ids: List[str], prechecks,
                    evaluator: Evaluator, ledger: UsageLedger, config: EvaluationConfig,
                    clock: Callable[[], datetime], past: Optional[HistoryRetrieval] = None) -> ClaudeReply:
    prompt = build_prompt(checked, stage_number, prechecks, past)
    input_tokens = evaluator.count_tokens(prompt)
    if input_tokens > config.max_input_tokens:
        raise EvaluationManualResolutionError(
            "INPUT_TOO_LARGE", f"stage {stage_number} needs {input_tokens} input tokens (limit {config.max_input_tokens})"
        )
    ledger.check_budget(input_tokens + config.max_tokens, clock())

    def spent(usage: Optional[TokenUsage], request_id: Optional[str]) -> None:
        if usage is not None:
            ledger.record(UsageRecord(recorded_at=clock(), comment_id=checked.comment_id, stage=stage_number,
                                      model=evaluator.model, request_id=request_id, usage=usage))

    try:
        reply = evaluator.evaluate(prompt)
    except EvaluationError as error:
        spent(error.usage, error.request_id)
        raise
    spent(reply.usage, reply.request_id)

    answered = set(reply.answer.passed_rule_ids) | {f.rule_id for f in reply.answer.findings}
    if answered != set(rule_ids):
        missing, extra = sorted(set(rule_ids) - answered), sorted(answered - set(rule_ids))
        raise RuleCoverageError(f"stage {stage_number} answer: missing {missing}, unexpected {extra}",
                                reply.usage, reply.request_id)
    return reply
