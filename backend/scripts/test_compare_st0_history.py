"""compare_st0_history.py and evaluate_demo.py with a scripted fake Claude:
no network, no key, no cost."""
import csv
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_st0_history  # noqa: E402
import evaluate_demo  # noqa: E402

from app.evaluation.fake import ScriptedEvaluator  # noqa: E402
from app.evaluation.history_comparison import estimate_cost, human_mentions, load_cases  # noqa: E402
from app.models import ClaudeStageAnswer  # noqa: E402

_STEP = "Stress Test 0 - Dataset & DS Problem"
_SUBMISSION = "<div>Dataset: retail sales.</div><ul><li>Problem: churn</li><li>Solution: classify</li></ul>"
_COLUMNS = ["BCP_ID", "StepName", "MessageId", "CommentId", "CommentCreatedDate", "MarkerType", "Comment",
            "StressTest", "CreatorName", "CreatorEmail"]


def _row(message_id, comment_id, minute, marker, comment, stress_test="0", by="student@example.com"):
    return {"BCP_ID": "77", "StepName": _STEP, "MessageId": str(message_id), "CommentId": str(comment_id),
            "CommentCreatedDate": f"2026-07-01 10:{minute:02d}:00.000", "MarkerType": marker, "Comment": comment,
            "StressTest": stress_test, "CreatorName": "Student Name", "CreatorEmail": by}


_REVIEWER = "reviewer@example.com"


@pytest.fixture
def history_csv(tmp_path):
    rows = [
        # thread 1: two critiques, then feedback -> the SECOND critique is the case
        _row(501, 1001, 1, "Critique", "<div>first draft ##Critique##</div>"),
        _row(501, 1002, 2, "Critique", _SUBMISSION + "<div>##Critique##</div>"),
        _row(501, 1003, 3, "FeedbackGiven", "<div>Please add the data source link. ##FeedbackGiven##</div>", by=_REVIEWER),
        _row(501, 1004, 4, "Critique", _SUBMISSION + "<div>fixed ##Critique##</div>"),
        # thread 2: critique and feedback
        _row(502, 2001, 1, "Critique", _SUBMISSION + "<div>##Critique##</div>"),
        _row(502, 2002, 2, "FeedbackGiven",
             "<div>Looks good, please highlight the selected problem. ##FeedbackGiven##</div>", by=_REVIEWER),
        # thread 5: the extract labels the reviewer's reply "Critique" (its first marker), and the
        # reviewer also posted a bare ##Critique##; the case must still be the student's comment
        _row(505, 5001, 1, "Critique", _SUBMISSION + "<div>##Critique##</div>"),
        _row(505, 5002, 2, "Critique", "<div>##Critique##</div>", by=_REVIEWER),
        _row(505, 5003, 3, "Critique", "<div>Re ##Critique##: add the link. ##FeedbackGiven##</div>", by=_REVIEWER),
        # thread 3: no feedback yet -> not a case
        _row(503, 3001, 1, "Critique", _SUBMISSION),
        # another Stress Test -> ignored
        _row(504, 4001, 1, "Critique", _SUBMISSION, stress_test="1"),
        _row(504, 4002, 2, "FeedbackGiven", "<div>x ##FeedbackGiven##</div>", stress_test="1", by=_REVIEWER),
    ]
    path = tmp_path / "comments.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")

    def _run(argv, evaluator):
        return compare_st0_history.main(argv, evaluator=evaluator, out_dir=tmp_path / "comparison",
                                        ledger_dir=tmp_path, env_file=tmp_path / "no.env")
    return _run


def test_cases_pair_the_first_feedback_with_the_critique_it_answered(history_csv):
    cases = load_cases(history_csv)
    assert [c.comment_id for c in cases] == [1002, 2001, 5001]
    assert "data source link" in cases[0].human_feedback_text
    assert cases[0].submission.title == _STEP
    # the case's thread stops at the critique: the answering feedback is never in it
    assert [c.comment_id for c in cases[0].submission.comments] == [1001, 1002]
    assert [c.comment_id for c in cases[2].submission.comments] == [5001]


def test_the_dry_run_counts_tokens_but_never_evaluates(history_csv, run, capsys):
    claude = ScriptedEvaluator(input_tokens=3000)  # no scripted answers: evaluating would fail the test
    assert run(["--csv", str(history_csv)], claude) == 0
    out = capsys.readouterr().out
    assert claude.prompts == []
    assert "3 cases, up to 6 calls" in out
    assert "Expected cost:" in out and "Worst-case cost:" in out
    assert "Nothing was evaluated" in out
    assert "Student Name" not in out and "student@example.com" not in out


def test_the_paid_run_needs_explicit_confirmation(history_csv, run, capsys):
    claude = ScriptedEvaluator()
    assert run(["--csv", str(history_csv), "--run"], claude) == 1
    assert claude.prompts == []
    assert "--yes" in capsys.readouterr().out


def _stage_1_fail():
    return ClaudeStageAnswer(passed_rule_ids=["ST0-001", "ST0-003", "ST0-006", "ST0-007", "ST0-008"], findings=[{
        "rule_id": "ST0-002", "status": "FAIL", "severity": "Required Fix", "evidence": "No link.",
        "reason": "ST0-002 needs one.", "suggested_feedback": "Please provide the public source link.",
        "confidence": 0.9}])


def test_the_paid_run_writes_a_report_and_never_pays_twice(history_csv, run, tmp_path):
    claude = ScriptedEvaluator(_stage_1_fail(), _stage_1_fail(), _stage_1_fail())
    assert run(["--csv", str(history_csv), "--run", "--yes"], claude) == 0
    report = (tmp_path / "comparison" / "report.md").read_text()
    assert "| ST0-002 | FAIL | yes |" in report  # the human asked for the source link too
    assert "AI FAIL and human mentioned the rule: 2" in report  # threads 501 and 505 asked for the link
    assert len(claude.prompts) == 3

    again = ScriptedEvaluator()  # would fail if called
    assert run(["--csv", str(history_csv), "--run", "--yes"], again) == 0
    assert again.prompts == []


def test_a_missing_key_is_a_configuration_error(history_csv, tmp_path, capsys):
    code = compare_st0_history.main(["--csv", str(history_csv)], evaluator=ScriptedEvaluator(),
                                    out_dir=tmp_path, ledger_dir=tmp_path, env_file=tmp_path / "no.env")
    assert code == 1
    assert "ANTHROPIC_API_KEY is missing" in capsys.readouterr().out


def test_a_missing_csv_is_an_input_error(tmp_path, run):
    assert run(["--csv", str(tmp_path / "nope.csv")], ScriptedEvaluator()) == 1


def test_the_cost_estimate_prices_cache_reads_below_writes():
    estimate = estimate_cost([3000, 2500, 3000, 2500], system_size=2000, max_tokens=4000)
    assert estimate.calls == 4 and estimate.input_tokens == 11000
    assert 0 < estimate.expected_usd < estimate.worst_case_usd
    # expected: 3000 uncached x $2 + 2000 x $2.50 + 3 x 2000 x $0.20 + 4 x 600 x $10, per 1M
    assert estimate.expected_usd == round((3000 * 2 + 2000 * 2.5 + 6000 * 0.2 + 2400 * 10) / 1e6, 4)


def test_human_mention_hints():
    assert human_mentions("Please add the source link and highlight the selected problem.") == ["ST0-002", "ST0-008"]


def test_the_demo_shows_all_three_acceptance_criteria(capsys):
    assert evaluate_demo.main() == 0
    out = capsys.readouterr().out
    assert "ST0-003 FAIL [Required Fix]" in out  # 1: structured draft findings
    assert "error: SUBMISSION_EMPTY" in out  # 2: invalid submission -> error
    assert "evaluation_finding     comment 2002 message 500 rule ST0-003" in out  # 3: submission + rule id
    assert "Claude calls in total: 1" in out  # replay did not call again


def test_the_env_file_key_wins_over_a_different_shell_key(history_csv, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-shell-key-from-another-project")
    env_file = tmp_path / "project.env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-project-key-from-dotenv\nEVALUATION_EFFORT=medium\n")
    seen = {}
    real = compare_st0_history.load_evaluation_config

    def spy(environ):
        config = real(environ)
        seen["key"], seen["effort"] = config.api_key.get_secret_value(), config.effort
        return config

    monkeypatch.setattr(compare_st0_history, "load_evaluation_config", spy)
    assert compare_st0_history.main(["--csv", str(history_csv)], evaluator=ScriptedEvaluator(),
                                    out_dir=tmp_path, ledger_dir=tmp_path, env_file=env_file) == 0
    assert seen == {"key": "sk-ant-project-key-from-dotenv", "effort": "medium"}
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-shell-key-from-another-project"  # shell left untouched
