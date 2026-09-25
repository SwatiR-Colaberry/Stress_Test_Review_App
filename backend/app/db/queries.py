"""Loads stored .sql files and runs metric-style (name, value) queries.

Stored queries live in backend/app/basecamp/sql/ and are read-only
(test_sql_queries.py enforces that). The connection passed in already carries
its per-query timeout (see connection.connect_with_retry).

A failed query raises DatabaseQueryError with a stable error_class and the
SQLSTATE, never the driver message. Queries are not retried here: a query
that timed out would most likely time out again, so the caller decides.
Every query logs one JSON line (db_query_completed / db_query_failed) with a
label, duration and row count; never the SQL text or parameters.
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import pyodbc
from pydantic import BaseModel

from app.db.connection import classify_error

logger = logging.getLogger("stress_test_review.db")

SQL_DIR = Path(__file__).resolve().parents[1] / "basecamp" / "sql"


class DatabaseQueryError(Exception):
    def __init__(self, error_class: str, sqlstate: Optional[str]) -> None:
        self.error_class = error_class
        self.sqlstate = sqlstate
        super().__init__(f"query failed: {error_class} (SQLSTATE {sqlstate or 'unknown'})")


class Metric(BaseModel):
    name: str
    value: int


def load_sql(name: str) -> str:
    path = (SQL_DIR / name).resolve()
    if path.parent != SQL_DIR.resolve() or path.suffix != ".sql":
        raise ValueError(f"not a stored query: {name}")
    return path.read_text()


def fetch_metrics(conn, sql: str, label: str = "metrics") -> List[Metric]:
    """Runs a query returning exactly two columns (metric name, integer value)."""
    _, rows = fetch_table(conn, sql, label=label)
    for row in rows:
        if len(row) != 2:
            raise ValueError(f"metric query must return 2 columns, got {len(row)}")
    return [Metric(name=str(name), value=int(value)) for name, value in rows]


def fetch_table(conn, sql: str, *params: Any, label: str = "query") -> Tuple[List[str], List[tuple]]:
    """Runs a query and returns (column names, rows). For small, reviewed
    result sets only; callers decide what is safe to print. `label` names the
    query in the log line (use the stored file name)."""
    started = time.monotonic()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, *params)
        executed_ms = _elapsed_ms(started)
        columns = [col[0] for col in cursor.description]
        rows = [tuple(row) for row in cursor.fetchall()]
    except pyodbc.Error as exc:
        error_class, sqlstate = classify_error(exc)
        _log(logging.WARNING, "db_query_failed", label=label, error_class=error_class, sqlstate=sqlstate,
             duration_ms=_elapsed_ms(started), outcome="failure")
        raise DatabaseQueryError(error_class, sqlstate) from None
    finally:
        cursor.close()
    _log(logging.INFO, "db_query_completed", label=label, rows=len(rows), execute_ms=executed_ms,
         duration_ms=_elapsed_ms(started), outcome="success")
    return columns, rows


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _log(level: int, event: str, **context: Any) -> None:
    line = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": logging.getLevelName(level).lower(),
            "service": "backend", "event": event, **context}
    logger.log(level, json.dumps(line))


BCP_ID_FILTER_MARKER = "/*BCP_ID_FILTER*/"
MAX_BCP_IDS = 100


def with_bcp_id_filter(sql: str, bcp_ids: Optional[Sequence[int]]) -> Tuple[str, List[int]]:
    """Restricts a stored query that carries the /*BCP_ID_FILTER*/ marker to the
    given projects. Only "?" placeholders are written into the SQL; the ids
    themselves are returned as parameters for the driver to bind. None means
    no filter (the marker is removed)."""
    if sql.count(BCP_ID_FILTER_MARKER) != 1:
        raise ValueError("query must contain the BCP_ID filter marker exactly once")
    if bcp_ids is None:
        return sql.replace(BCP_ID_FILTER_MARKER, ""), []
    ids = list(dict.fromkeys(bcp_ids))  # de-duplicate, keep order
    if not ids or len(ids) > MAX_BCP_IDS:
        raise ValueError(f"between 1 and {MAX_BCP_IDS} project ids are required")
    if not all(isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in ids):
        raise ValueError("project ids must be positive integers")
    clause = "AND p.BCP_ID IN (" + ", ".join("?" for _ in ids) + ")"
    return sql.replace(BCP_ID_FILTER_MARKER, clause), ids
