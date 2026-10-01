"""One-off operational script: bring the newest real Stress Test 0 request
into the app and serve it, for a live trial (user decision 2026-10-01).

Nothing watches SQL Server for new requests yet, and the Review Queue lives
in the server's memory, so this script does the whole path in ONE process:
  1. reads the newest ST0 thread with a ##Critique## request from SQL Server
     (SELECT only: app/basecamp/sql/st0_newest_request.sql);
  2. puts the request in the Review Queue (intake, audited);
  3. has Claude write the draft findings: a PAID call of about 1-2 cents,
     never repeated for the same request (results in data/evaluations/).
     Rules that need an image (ST0-004) see the screenshot part's last image,
     downloaded from Basecamp with the posting app's token, kept in memory;
  4. serves the app on http://localhost:8000. Sign in again (sessions are in
     memory) and the review is in the queue. Posting to Basecamp stays off.

Without --yes it stops after step 1 (free, writes nothing). Prints ids, dates
and counts only: names, emails and comment text are student data and appear
in the signed-in pages only. Stop the normal server first (same port).

Run from the repo root:
  .venv/bin/python backend/scripts/live_trial.py         # step 1 only
  .venv/bin/python backend/scripts/live_trial.py --yes   # all four steps
Exit codes: 0 ok, 1 configuration problem, 2 database unavailable or no
request found, 3 port in use, 4 audit trail could not be written.
"""
import argparse
import os
import socket
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import dotenv_values, load_dotenv  # noqa: E402

from app.db.config import DatabaseConfigError, load_database_config  # noqa: E402
from app.db.connection import DatabaseConnectionError, connect_with_retry  # noqa: E402
from app.db.queries import DatabaseQueryError, fetch_table, load_sql  # noqa: E402
from app.review_queue.live_request import LiveRequest, NoRequestFound, newest_request  # noqa: E402

QUERY = "st0_newest_request.sql"
HOST = "127.0.0.1"


def read_newest_thread() -> List[Dict[str, Any]]:
    conn = connect_with_retry(load_database_config())
    try:
        columns, rows = fetch_table(conn, load_sql(QUERY), label=QUERY)
    finally:
        conn.close()
    return [dict(zip(columns, values)) for values in rows]


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex((HOST, port)) != 0


def describe(live: LiveRequest) -> None:
    print(f"Newest ST0 request: comment {live.comment.comment_id} in thread {live.comment.message_id} "
          f"(project {live.project_bcp_id}), posted {live.comment.created_at:%Y-%m-%d %H:%M} UTC")
    print(f"Thread: {len(live.submission.comments)} comment(s) up to the request, "
          f"{live.later_comments} after it{' (it may already have feedback)' if live.later_comments else ''}")


def image_source(live: LiveRequest):
    """The request comment's images through the Basecamp API, or None (images then NOT_FETCHED)."""
    from app.basecamp.config import BasecampConfigError, load_basecamp_config
    from app.basecamp.image_source import CommentImageSource
    if live.comment.project_id is None:
        print("Images off: the thread's Basecamp project is not known")
        return None
    try:
        return CommentImageSource(load_basecamp_config(), live.comment.project_id, live.comment.comment_id)
    except BasecampConfigError as exc:
        print(f"Images off, Basecamp settings: {exc}")
        return None


def queue_and_evaluate(live: LiveRequest, evaluation_env: Dict[str, str], evaluator=None,
                       images: Optional[Callable] = None) -> int:
    """Steps 2 and 3, into the same stores the served app uses."""
    from app.audit.dependencies import get_audit_trail
    from app.audit.trail import AuditWriteError
    from app.evaluation.claude_client import AnthropicEvaluator, EvaluationError
    from app.evaluation import config as evaluation_config
    from app.evaluation.evaluate import EvaluationManualResolutionError, evaluate_submission
    from app.evaluation.input_check import SubmissionIncompleteError
    from app.evaluation.store import (DEFAULT_DIR, DailyTokenLimitExceededError, EvaluationInProgressError,
                                      EvaluationStoreError, ResultStore, UsageLedger)
    from app.review_queue.dependencies import get_review_queue_store
    from app.review_queue.intake import process_comment
    from app.rules.loader import load_rules

    audit = get_audit_trail()
    try:
        intake = process_comment(live.comment.model_dump(), get_review_queue_store(), audit)
    except AuditWriteError as exc:
        print(f"AUDIT TRAIL UNAVAILABLE ({exc.error_class}): nothing queued; safe to re-run")
        return 4
    print(f"Review Queue: {intake.outcome}, review {intake.review_id}")

    try:
        config = evaluation_config.load_evaluation_config(evaluation_env)
    except evaluation_config.EvaluationConfigError as exc:
        print(f"AI draft skipped, configuration: {exc}")
        return 0
    results = Path(os.environ.get("EVALUATIONS_DIR") or DEFAULT_DIR)
    rules = load_rules(live.step_name, audit, actor_id="live-trial", comment_id=live.comment.comment_id)
    try:
        result = evaluate_submission(
            live.submission, live.comment.comment_id, rules, evaluator=evaluator or AnthropicEvaluator(config),
            store=ResultStore(results), ledger=UsageLedger(results, daily_limit=config.daily_token_limit),
            audit=audit, config=config, actor_id="live-trial", images=images)
    except (SubmissionIncompleteError, EvaluationManualResolutionError) as exc:
        print(f"AI draft not made, needs a person: {exc.reason_code}")
        return 0
    except (EvaluationError, EvaluationStoreError, EvaluationInProgressError, DailyTokenLimitExceededError) as exc:
        print(f"AI draft failed ({getattr(exc, 'error_class', type(exc).__name__)}); the review is queued without it")
        return 0
    print(f"AI draft: {len(result.findings)} finding(s), {sum(f.status == 'FAIL' for f in result.findings)} FAIL, "
          f"stages {result.stages_evaluated}, {result.usage.total} tokens")
    for note in result.images:
        print(f"Image for {note.rule_id}: {note.outcome}")
    return 0


def serve(port: int) -> None:
    import uvicorn

    from app.main import app
    print(f"Serving on http://localhost:{port}/queue/  (Ctrl+C to stop; the queue is cleared when it stops)")
    uvicorn.run(app, host=HOST, port=port)


def main(argv: Optional[List[str]] = None, read_rows: Callable[[], List[Dict[str, Any]]] = read_newest_thread,
         evaluator=None, run_server: Callable[[int], None] = serve, env_file: Path = REPO_ROOT / ".env",
         images: Optional[Callable] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="queue it, make the PAID AI draft, and serve")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    load_dotenv(env_file, override=False)  # real environment variables win over .env...
    # ...except for the Claude settings: a different ANTHROPIC_API_KEY left in the shell by another
    # project must not be used (found in the first live run). Read into the config only, as
    # compare_st0_history.py does; never copied into os.environ.
    file_values = {name: value for name, value in dotenv_values(env_file).items() if value is not None}
    evaluation_env = {**os.environ, **file_values}

    try:
        live = newest_request(read_rows())
    except DatabaseConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1
    except (DatabaseConnectionError, DatabaseQueryError) as exc:
        print(f"DATABASE UNAVAILABLE: {exc}")
        return 2
    except NoRequestFound as exc:
        print(f"NO REQUEST: {exc}")
        return 2
    describe(live)
    if not args.yes:
        print("Nothing written. To queue it, make the paid AI draft (about 1-2 cents) and serve: --yes")
        return 0
    if not port_free(args.port):
        print(f"PORT {args.port} IN USE: stop the other server first; nothing was queued")
        return 3
    code = queue_and_evaluate(live, evaluation_env, evaluator, images or image_source(live))
    if code:
        return code
    run_server(args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
