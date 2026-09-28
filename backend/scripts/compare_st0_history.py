"""One-off operational script: compare Claude's ST0 draft findings with the
human feedback on historical ST0 submissions (STORY-004), before the AI
evaluation is switched on.

Default is a FREE dry run: it builds the real Stage 1 and Stage 2 prompts and
asks the token-counting endpoint (count_tokens, no charge) how big they are,
then prints a cost estimate. Nothing is evaluated and nothing is stored.

--run --yes makes the PAID calls. Results go to a separate store
(data/evaluations/comparison/), so re-running never pays twice for a case;
usage goes to the shared ledger, so the daily token limit applies; audit
events go to a scratch trail in the same folder, not the real one. The
report (git-ignored: it quotes student and reviewer text) is written to
data/evaluations/comparison/report.md. Prints counts and costs only.

Run from the repo root:
  .venv/bin/python backend/scripts/compare_st0_history.py              # dry run, free
  .venv/bin/python backend/scripts/compare_st0_history.py --run --yes  # paid
Needs ANTHROPIC_API_KEY in .env (see .env.example); values in .env win over the shell.
Exit codes: 0 ok, 1 configuration/input problem, 2 key rejected,
3 Claude unavailable or a case failed, 4 daily token limit reached.
"""
import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import dotenv_values  # noqa: E402

from app.audit.trail import InMemoryAuditTrail, JsonlFileAuditTrail  # noqa: E402
from app.evaluation.claude_client import AnthropicEvaluator, ClaudeAuthError, EvaluationError, Evaluator  # noqa: E402
from app.evaluation.config import EvaluationConfig, EvaluationConfigError, load_evaluation_config  # noqa: E402
from app.evaluation.evaluate import EvaluationManualResolutionError, evaluate_submission  # noqa: E402
from app.evaluation.history_comparison import Case, estimate_cost, load_cases, render_report  # noqa: E402
from app.evaluation.input_check import SubmissionIncompleteError, prepare_evaluation_input  # noqa: E402
from app.evaluation.prechecks import run_prechecks  # noqa: E402
from app.evaluation.prompt import EvaluationPrompt, build_prompt, build_system_prompt  # noqa: E402
from app.evaluation.store import (  # noqa: E402
    DEFAULT_DIR, DailyTokenLimitExceededError, EvaluationStoreError, ResultStore, UsageLedger,
)
from app.logging_config import configure_logging  # noqa: E402
from app.models import EvaluationResult  # noqa: E402
from app.rules.loader import load_rules  # noqa: E402

DEFAULT_CSV = REPO_ROOT / "data" / "extracts" / "2026-09-25-per-stress-test" / "comments.csv"


def dry_run(cases: List[Case], evaluator: Evaluator, config: EvaluationConfig) -> int:
    scratch = InMemoryAuditTrail()  # rule loading records an event; keep it out of the real trail
    stage_tokens: List[int] = []
    system_tokens: Optional[int] = None
    print(f"{'comment':>12} {'stage 1':>8} {'stage 2':>8}  (input tokens, from count_tokens)")
    for case in cases:
        rules = load_rules(case.step_name, scratch)
        try:
            checked = prepare_evaluation_input(case.submission, case.comment_id, rules)
        except SubmissionIncompleteError as exc:
            print(f"{case.comment_id:>12} skipped: {exc.reason_code}")
            continue
        if system_tokens is None:
            system_tokens = evaluator.count_tokens(EvaluationPrompt(system=build_system_prompt(checked.module), user="."))
        prechecks = run_prechecks(checked)
        counts = [evaluator.count_tokens(build_prompt(checked, stage, prechecks)) for stage in (1, 2)]
        stage_tokens += counts
        over = " OVER LIMIT -> manual resolution" if max(counts) > config.max_input_tokens else ""
        print(f"{case.comment_id:>12} {counts[0]:>8} {counts[1]:>8}{over}")
    if not stage_tokens:
        print("No evaluable cases.")
        return 1
    estimate = estimate_cost(stage_tokens, system_tokens or 0, config.max_tokens)
    print(f"\n{len(stage_tokens) // 2} cases, up to {estimate.calls} calls ({config.model}, effort {config.effort})")
    print(f"Input tokens: {estimate.input_tokens} (system prompt {estimate.cached_tokens}, cached after the first call)")
    print(f"Expected cost:   ${estimate.expected_usd:.2f}  (both stages for every case, ~600 output tokens per call)")
    print(f"Worst-case cost: ${estimate.worst_case_usd:.2f}  (no cache hits, every call at max_tokens={config.max_tokens})")
    print("Nothing was evaluated. To make the paid calls: --run --yes")
    return 0


def paid_run(cases: List[Case], evaluator: Evaluator, config: EvaluationConfig, out_dir: Path,
             ledger_dir: Path) -> int:
    audit = JsonlFileAuditTrail(out_dir / "audit_trail.jsonl")
    store, ledger = ResultStore(out_dir), UsageLedger(ledger_dir, daily_limit=config.daily_token_limit)
    results: Dict[int, Optional[EvaluationResult]] = {}
    errors: Dict[int, str] = {}
    exit_code = 0
    for case in cases:
        rules = load_rules(case.step_name, audit, comment_id=case.comment_id)
        try:
            results[case.comment_id] = evaluate_submission(
                case.submission, case.comment_id, rules, evaluator=evaluator, store=store, ledger=ledger,
                audit=audit, config=config, actor_id="st0-history-comparison",
            )
            outcome = results[case.comment_id]
            print(f"{case.comment_id:>12} stages {outcome.stages_evaluated} "
                  f"FAIL {sum(f.status == 'FAIL' for f in outcome.findings)} "
                  f"ADVISORY {sum(f.status == 'ADVISORY' for f in outcome.findings)} tokens {outcome.usage.total}")
        except ClaudeAuthError as exc:
            print(f"KEY REJECTED: {exc}")
            return 2
        except DailyTokenLimitExceededError as exc:
            print(f"STOPPED: {exc}")
            errors[case.comment_id], exit_code = "daily token limit", 4
            break
        except (SubmissionIncompleteError, EvaluationManualResolutionError) as exc:
            results[case.comment_id], errors[case.comment_id] = None, f"{type(exc).__name__}: {exc.reason_code}"
            print(f"{case.comment_id:>12} {errors[case.comment_id]}")
        except (EvaluationError, EvaluationStoreError) as exc:
            results[case.comment_id], errors[case.comment_id] = None, f"{exc.error_class}: {exc}"
            print(f"{case.comment_id:>12} FAILED {exc.error_class}")
            exit_code = 3
    report = out_dir / "report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(cases, results, errors), encoding="utf-8")
    print(f"Report: {report.relative_to(REPO_ROOT) if report.is_relative_to(REPO_ROOT) else report}")
    return exit_code


def main(argv: Optional[List[str]] = None, evaluator: Optional[Evaluator] = None,
         out_dir: Path = DEFAULT_DIR / "comparison", ledger_dir: Path = DEFAULT_DIR,
         env_file: Path = REPO_ROOT / ".env") -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="history extract (comments.csv)")
    parser.add_argument("--run", action="store_true", help="make the PAID evaluation calls")
    parser.add_argument("--yes", action="store_true", help="confirm the paid run")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases")
    args = parser.parse_args(argv)
    configure_logging()

    if args.run and not args.yes:
        print("The paid run needs --yes as well. Run without --run first to see the cost estimate.")
        return 1
    if not args.csv.exists():
        print(f"INPUT ERROR: {args.csv} not found")
        return 1
    # .env wins over the shell: the project's key lives in .env (user decision),
    # and a different ANTHROPIC_API_KEY left in the shell must not be used.
    # Read into the config only, never copied into os.environ.
    file_values = {name: value for name, value in dotenv_values(env_file).items() if value is not None}
    try:
        config = load_evaluation_config({**os.environ, **file_values})
    except EvaluationConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1
    evaluator = evaluator or AnthropicEvaluator(config)
    cases = load_cases(args.csv)[: args.limit]
    print(f"{len(cases)} ST0 cases from {args.csv.name}")
    try:
        if args.run:
            return paid_run(cases, evaluator, config, out_dir, ledger_dir)
        return dry_run(cases, evaluator, config)
    except ClaudeAuthError as exc:
        print(f"KEY REJECTED: {exc}")
        return 2
    except EvaluationError as exc:
        print(f"CLAUDE UNAVAILABLE: {exc.error_class}: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
