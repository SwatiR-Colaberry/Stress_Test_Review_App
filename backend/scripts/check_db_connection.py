"""One-off operational script (Step 3 of directives/ST-historical-comment-extraction.md):
check the SQL Server connection and the schema the ST history queries rely on.

Read-only. Prints server facts and table/column metadata only: no row data,
no password, no driver error text. Safe to run any number of times.

Run from the repo root:  .venv/bin/python backend/scripts/check_db_connection.py
Exit codes: 0 ok, 1 configuration problem, 2 cannot connect, 3 schema problem.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

from app.db.config import DatabaseConfigError, load_database_config  # noqa: E402
from app.db.connection import DatabaseConnectionError, connect_with_retry  # noqa: E402
from app.db.inspection import inspect_database  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402

_HINTS = {
    "AuthError": "Login rejected. Check DB_USERNAME / DB_PASSWORD in .env (not retried, to avoid account lockout).",
    "UpstreamUnavailable": "Server not reachable. Check DB_SERVER, VPN/network access, and firewall rules.",
    "TimeoutError": "Timed out. Check network/VPN, or raise DB_CONNECT_TIMEOUT_S.",
    "TlsCertificateError": (
        "The server's TLS certificate is not trusted by this machine (typically self-signed). "
        "Either install the server's/company CA certificate from IT (then keep DB_TRUST_SERVER_CERTIFICATE=no), "
        "or set DB_TRUST_SERVER_CERTIFICATE=yes in .env: still encrypted, but the server identity is not verified."
    ),
    "DriverNotFound": "ODBC driver not found. Check DB_DRIVER matches `odbcinst -q -d` (brew install msodbcsql18).",
}


def main() -> int:
    configure_logging()
    env_file = REPO_ROOT / ".env"
    load_dotenv(env_file, override=False)  # real environment variables win over .env
    print(f".env file: {'found' if env_file.is_file() else 'NOT FOUND (using process environment only)'}")

    try:
        config = load_database_config()
    except DatabaseConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1
    print(f"Connecting: driver={config.driver!r}, encrypt={config.encrypt}, timeout={config.connect_timeout_s}s")

    try:
        conn = connect_with_retry(config)
    except DatabaseConnectionError as exc:
        print(f"CONNECTION FAILED: {exc}")
        print(f"Hint: {_HINTS.get(exc.error_class, 'Unclassified database error; check the SQLSTATE above.')}")
        return 2
    try:
        report = inspect_database(conn)
    finally:
        conn.close()

    print(f"\nServer: SQL Server {report.product_version} ({report.edition})")
    print(f"Full-Text Search installed: {report.full_text_installed}")
    print(f"Login can INSERT into comments table: {report.login_can_insert_comments}"
          + ("  <- WARNING: ask IT/DBA for a read-only login" if report.login_can_insert_comments else ""))
    print("\nColumns:")
    current = None
    for col in report.columns:
        if col.table != current:
            current = col.table
            print(f"  {current}")
        length = "(max)" if col.max_length == -1 else (f"({col.max_length})" if col.max_length else "")
        print(f"    {col.column:<34} {col.data_type}{length}{'' if col.nullable else ' NOT NULL'}")
    for label, items in (("Missing tables", report.missing_tables), ("Missing columns", report.missing_columns),
                         ("ID column problems", report.id_column_problems), ("Notes", report.id_column_notes)):
        if items:
            print(f"\n{label}:")
            for item in items:
                print(f"  - {item}")
    print("\nRESULT: " + ("OK - schema matches the stored queries." if report.ok else "SCHEMA PROBLEMS - see above."))
    return 0 if report.ok else 3


if __name__ == "__main__":
    sys.exit(main())
