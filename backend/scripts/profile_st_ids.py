"""One-off operational script: run st_id_profile.sql (counts only) against
SQL Server and print the metrics. Read-only; prints no row values.
Decides how the ST history queries should join (see
directives/ST-historical-comment-extraction.md).

Run from the repo root:  .venv/bin/python backend/scripts/profile_st_ids.py
Exit codes: 0 ok, 1 configuration problem, 2 cannot connect, 4 query failed.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

from app.db.config import DatabaseConfigError, load_database_config  # noqa: E402
from app.db.connection import DatabaseConnectionError, connect_with_retry  # noqa: E402
from app.db.queries import DatabaseQueryError, fetch_metrics, load_sql  # noqa: E402
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
        metrics = fetch_metrics(conn, load_sql("st_id_profile.sql"), label="st_id_profile.sql")
    except DatabaseQueryError as exc:
        print(f"QUERY FAILED: {exc}")
        return 4
    finally:
        conn.close()
    width = max(len(m.name) for m in metrics)
    for m in metrics:
        print(f"{m.name:<{width}}  {m.value:>12,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
