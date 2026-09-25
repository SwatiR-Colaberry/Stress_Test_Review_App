"""One-off operational script: list the candidate projects for the ST0-ST5
history extraction (st_history_selection.sql): up to 15 per Stress Test,
most recent first. Prints project ids and counts
only (no names, emails, step names or comment text). Read-only.

Run from the repo root:  .venv/bin/python backend/scripts/select_st_projects.py
Exit codes: 0 ok, 1 configuration problem, 2 cannot connect, 4 query failed.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

from app.db.config import DatabaseConfigError, load_database_config  # noqa: E402
from app.db.connection import DatabaseConnectionError, connect_with_retry  # noqa: E402
from app.db.queries import DatabaseQueryError, fetch_table, load_sql  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402


def main() -> int:
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
        columns, rows = fetch_table(conn, load_sql("st_history_selection.sql"), label="st_history_selection.sql")
    except DatabaseQueryError as exc:
        print(f"QUERY FAILED: {exc}")
        return 4
    finally:
        conn.close()
    widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(c) for i, c in enumerate(columns)]
    print("  ".join(f"{c:>{w}}" for c, w in zip(columns, widths)))
    for row in rows:
        print("  ".join(f"{str(v):>{w}}" for v, w in zip(row, widths)))
    per_test = {}
    for row in rows:
        per_test[row[0]] = per_test.get(row[0], 0) + 1
    summary = ", ".join(f"ST{test}: {count}" for test, count in sorted(per_test.items()))
    distinct = len({row[2] for row in rows})
    print(f"\n{len(rows)} (project, Stress Test) pairs selected; {distinct} distinct projects. {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
