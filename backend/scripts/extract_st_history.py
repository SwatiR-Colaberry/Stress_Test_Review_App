"""One-off operational script (Step 5-6 of directives/ST-historical-comment-extraction.md):
extract the full ST0-ST5 comment history and critiquer assignments for the
approved projects, then verify it.

Writes to data/extracts/<YYYY-MM-DD>/ (git-ignored: contains personal data):
  comments.csv, steps.csv (one row per step, with StepHTML),
  critiquer_assignments.csv, summary.json (counts only).
Prints the summary only: no comment text, names or emails. Read-only against
SQL Server; re-running on the same day overwrites the same files.

Run from the repo root:
  .venv/bin/python backend/scripts/extract_st_history.py --bcp-ids 2148,2075,...
Exit codes: 0 ok, 1 configuration/argument problem, 2 cannot connect,
4 query failed, 5 extract written but verification failed.
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

from app.db.config import DatabaseConfigError, load_database_config  # noqa: E402
from app.db.connection import DatabaseConnectionError, connect_with_retry  # noqa: E402
from app.db.queries import DatabaseQueryError, fetch_table, load_sql, with_bcp_id_filter  # noqa: E402
from app.history.extract import annotate_markers, attach_critiquers, summarise, to_rows, write_csv  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402

ADDED_COLUMNS = ["StressTest", "PyMarkers", "MarkerAgrees", "AssignedCritiquer", "ThreadCritiquer"]


def _parse_ids(text: str):
    try:
        ids = [int(part) for part in text.split(",") if part.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError("--bcp-ids must be comma-separated whole numbers") from None
    if not ids:
        raise argparse.ArgumentTypeError("--bcp-ids needs at least one id")
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bcp-ids", type=_parse_ids, required=True, help="approved project ids, comma-separated")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data" / "extracts" / date.today().isoformat())
    args = parser.parse_args()

    configure_logging()
    load_dotenv(REPO_ROOT / ".env", override=False)
    try:
        config = load_database_config()
        comments_sql, comment_params = with_bcp_id_filter(load_sql("st_history_comments.sql"), args.bcp_ids)
        assign_sql, assign_params = with_bcp_id_filter(load_sql("st_critiquer_assignments.sql"), args.bcp_ids)
        steps_sql, steps_params = with_bcp_id_filter(load_sql("st_history_steps.sql"), args.bcp_ids)
    except (DatabaseConfigError, ValueError) as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1
    try:
        conn = connect_with_retry(config)
    except DatabaseConnectionError as exc:
        print(f"CONNECTION FAILED: {exc} (run check_db_connection.py for a hint)")
        return 2
    try:
        comment_cols, comment_rows = fetch_table(conn, comments_sql, *comment_params, label="st_history_comments.sql")
        assign_cols, assign_rows = fetch_table(conn, assign_sql, *assign_params, label="st_critiquer_assignments.sql")
        steps_cols, steps_rows = fetch_table(conn, steps_sql, *steps_params, label="st_history_steps.sql")
    except DatabaseQueryError as exc:
        print(f"QUERY FAILED: {exc}")
        return 4
    finally:
        conn.close()

    comments = to_rows(comment_cols, comment_rows)
    assignments = to_rows(assign_cols, assign_rows)
    steps = to_rows(steps_cols, steps_rows)
    annotate_markers(comments)
    attach_critiquers(comments, assignments)
    summary = summarise(comments, assignments, steps, args.bcp_ids)

    out = args.out_dir
    write_csv(out / "comments.csv", comments, comment_cols + ADDED_COLUMNS)
    write_csv(out / "critiquer_assignments.csv", assignments, assign_cols)
    write_csv(out / "steps.csv", steps, steps_cols)
    meta = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "bcp_ids": sorted(set(args.bcp_ids)),
        "queries": ["st_history_comments.sql", "st_critiquer_assignments.sql", "st_history_steps.sql"],
        "summary": summary.model_dump(),
        "verification_ok": summary.ok,
    }
    tmp = out / ".summary.json.tmp"
    tmp.write_text(json.dumps(meta, indent=2) + "\n")
    tmp.replace(out / "summary.json")

    try:
        shown = out.relative_to(REPO_ROOT)
    except ValueError:
        shown = out
    print(f"Wrote {shown}/ (comments.csv, steps.csv, critiquer_assignments.csv, summary.json)\n")
    for key, value in summary.model_dump().items():
        print(f"{key:<34} {value}")
    print("\nVERIFICATION: " + ("OK" if summary.ok else
          "FAILED - see duplicate_comment_ids / projects_missing / comments_without_step_row"))
    return 0 if summary.ok else 5


if __name__ == "__main__":
    sys.exit(main())
