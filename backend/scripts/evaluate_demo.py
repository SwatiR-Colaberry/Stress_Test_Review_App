"""Demo script: STORY-004 acceptance, end to end, with a FAKE Claude.

Free and offline: no API key, no network, nothing written outside a
temporary folder. Shows the three acceptance criteria:
  1. a valid submission -> structured draft findings;
  2. an invalid (empty) submission -> an error, and Claude is not called;
  3. Trust: every evaluation event in the audit trail carries the
     submission id (comment id) and the rule id;
plus idempotency: evaluating the same version again does not call Claude.

Run from the repo root:
  .venv/bin/python backend/scripts/evaluate_demo.py
"""
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.audit.trail import InMemoryAuditTrail  # noqa: E402
from app.evaluation.config import EvaluationConfig  # noqa: E402
from app.evaluation.evaluate import evaluate_submission  # noqa: E402
from app.evaluation.fake import ScriptedEvaluator  # noqa: E402
from app.evaluation.input_check import SubmissionIncompleteError  # noqa: E402
from app.evaluation.store import ResultStore, UsageLedger  # noqa: E402
from app.models import ClaudeStageAnswer, DraftFinding, Submission, SubmissionComment  # noqa: E402
from app.rules.loader import load_rules  # noqa: E402

_NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
_PROBLEM = ("<li>Problem: churn</li><li>Solution: classify</li><li>Model Type: supervised</li>"
            "<li>Algorithm: XGBoost</li><li>Independent Variables: tenure</li><li>Dependent Variable: churned</li>"
            "<li>Target Audience: marketing</li><li>Future Capability: retention</li>")
VALID_HTML = (
    "<div>Dataset: monthly retail sales for 45 stores, 2010-2012.</div>"
    '<div>Source: <a href="https://www.kaggle.com/datasets/demo/retail">Kaggle</a></div>'
    + "".join(f"<ul>{_PROBLEM}</ul>" for _ in range(9))
    + '<div><span style="background-color: rgb(250, 247, 133);">Selected problem: Problem 3</span></div>'
    + "<div>##Critique##</div>"
)


def _submission(comment_id: int, html: str) -> Submission:
    return Submission(
        message_id=500, title="Stress Test 0 - Dataset & DS Problem", created_at=_NOW, content_html="",
        comments=[SubmissionComment(comment_id=comment_id, created_at=_NOW, content_html=html)],
    )


def main() -> int:
    print("DEMO MODE: fake Claude, no API calls, nothing saved outside a temporary folder.\n")
    audit = InMemoryAuditTrail()
    config = EvaluationConfig(api_key="fake-key-never-sent", model="fake-claude")
    rules = load_rules("Stress Test 0 - Dataset & DS Problem", audit)
    stage_1 = ClaudeStageAnswer(
        passed_rule_ids=["ST0-001", "ST0-002", "ST0-006", "ST0-007", "ST0-008"],
        findings=[DraftFinding(
            rule_id="ST0-003", status="FAIL", severity="Required Fix",
            evidence="No sentence explains how the sales data was collected or compiled.",
            reason="ST0-003 needs a data collection explanation separate from the description.",
            suggested_feedback="Please add a brief explanation of how the data was collected or compiled.",
            confidence=0.85,
        )],
    )
    claude = ScriptedEvaluator(stage_1)
    with tempfile.TemporaryDirectory() as folder:
        env = dict(evaluator=claude, store=ResultStore(Path(folder)), ledger=UsageLedger(Path(folder)),
                   audit=audit, config=config, actor_id="demo")

        print("1. Valid submission (comment 2002)")
        result = evaluate_submission(_submission(2002, VALID_HTML), 2002, rules, **env)
        print(f"   stages evaluated: {result.stages_evaluated} (Stage 1 failed, so Stage 2 was not sent)")
        print(f"   passed: {', '.join(result.passed_rule_ids)}")
        for finding in result.findings:
            print(f"   {finding.rule_id} {finding.status} [{finding.severity}] confidence {finding.confidence}")
            print(f"      evidence: {finding.evidence}")
            print(f"      feedback: {finding.suggested_feedback}")
        print(f"   pre-checks: {result.prechecks.model_dump()}")

        print("\n2. Invalid submission (comment 3003: empty)")
        try:
            evaluate_submission(_submission(3003, "<div> </div>"), 3003, rules, **env)
        except SubmissionIncompleteError as exc:
            print(f"   error: {exc.reason_code} - {exc}")

        print("\n3. Same version again (comment 2002)")
        again = evaluate_submission(_submission(2002, VALID_HTML), 2002, rules, **env)
        print(f"   same result returned: {again == result}; Claude calls in total: {len(claude.prompts)}")

    print("\nAudit trail (Trust: submission id + rule id on every evaluation event):")
    for event in audit.read_all():
        if event.action.startswith("evaluation_"):
            print(f"   {event.action:<22} comment {event.comment_id} message {event.message_id} "
                  f"rule {event.rule_id or '-':<8} {event.reason_code or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
