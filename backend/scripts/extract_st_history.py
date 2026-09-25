"""One-off operational script (Step 5-6 of directives/ST-historical-comment-extraction.md):
extract the full ST0-ST5 comment history and critiquer assignments for the
approved projects, then verify it.

Writes to data/extracts/<YYYY-MM-DD>/ (git-ignored: contains personal data):
  comments.csv, steps.csv (one row per step, with StepHTML),
  critiquer_assignments.csv, summary.json (counts only).
Prints the summary only: no comment text, names or emails. Read-only against
SQL Server; re-running on the same day overwrites the same files.

Run from the repo root, either for whole projects:
  .venv/bin/python backend/scripts/extract_st_history.py --bcp-ids 2148,2075,...
or per Stress Test (runs st_history_selection.sql first: the 15 most recent
approved projects for each of ST0-ST5, and keeps only those Stress Test
threads of each project):
  .venv/bin/python backend/scripts/extract_st_history.py --per-stress-test
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
from app.history.extract import (  # noqa: E402
    annotate_markers,
    attach_critiquers,
    keep_selected_pairs,
    summarise,
    to_rows,
    write_csv,
)
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
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bcp-ids", type=_parse_ids, help="approved project ids, comma-separated (all their Stress Tests)")
    mode.add_argument("--per-stress-test", action="store_true",
                      help="select 15 projects per Stress Test with st_history_selection.sql and extract only those threads")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data" / "extracts" / date.today().isoformat())
    args = parser.parse_args()

    configure_logging()
    load_dotenv(REPO_ROOT / ".env", override=False)
    try:
        config = load_database_config()
    except DatabaseConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1
    try:
        conn = connect_with_retry(config)
    except DatabaseConnectionError as exc:
        print(f"CONNECTION FAILED: {exc} (run check_db_connection.py for a hint)")
        return 2
    try:
        pairs = None
        bcp_ids = args.bcp_ids
        if args.per_stress_test:
            sel_cols, sel_rows = fetch_table(conn, load_sql("st_history_selection.sql"), label="st_history_selection.sql")
            pairs = {(int(row["BCP_ID"]), str(row["StressTest"])) for row in to_rows(sel_cols, sel_rows)}
            bcp_ids = sorted({bcp_id for bcp_id, _test in pairs})
            if not pairs:
                print("SELECTION EMPTY: st_history_selection.sql returned no complete reviews; nothing extracted.")
                return 4
        try:
            comments_sql, comment_params = with_bcp_id_filter(load_sql("st_history_comments.sql"), bcp_ids)
            assign_sql, assign_params = with_bcp_id_filter(load_sql("st_critiquer_assignments.sql"), bcp_ids)
            steps_sql, steps_params = with_bcp_id_filter(load_sql("st_history_steps.sql"), bcp_ids)
        except ValueError as exc:
            print(f"CONFIG ERROR: {exc}")
            return 1
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
    if pairs is not None:
        comments, steps, assignments = keep_selected_pairs(comments, steps, assignments, pairs)
    attach_critiquers(comments, assignments)
    summary = summarise(comments, assignments, steps, bcp_ids, pairs)

    out = args.out_dir
    write_csv(out / "comments.csv", comments, comment_cols + ADDED_COLUMNS)
    write_csv(out / "critiquer_assignments.csv", assignments, assign_cols)
    write_csv(out / "steps.csv", steps, steps_cols)
    meta = {
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "bcp_ids": sorted(set(bcp_ids)),
        "selection": sorted(f"{bcp_id}/ST{test}" for bcp_id, test in pairs) if pairs else None,
        "queries": (["st_history_selection.sql"] if pairs else [])
        + ["st_history_comments.sql", "st_critiquer_assignments.sql", "st_history_steps.sql"],
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
          "FAILED - see duplicate_comment_ids / projects_missing / comments_without_step_row / pairs_missing"))
    return 0 if summary.ok else 5


if __name__ == "__main__":
    sys.exit(main())
