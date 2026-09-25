"""Opens a SQL Server connection with an explicit timeout and capped retries.

Failure handling:
- Retries only transient failures: cannot reach the server (SQLSTATE 08001,
  08S01) and timeouts (HYT00, HYT01). At most max_attempts (default 3).
- Login failures, an untrusted server certificate, a missing driver, or
  anything else are not retried: trying again would fail the same way (and
  repeated bad logins can lock an account).
- An untrusted TLS certificate is reported as TlsCertificateError. The driver
  gives it the same SQLSTATE (08001) as "server unreachable", so it is told
  apart by a keyword in the driver message; the message is inspected here
  and then discarded, never logged.
- On failure raises DatabaseConnectionError carrying a stable error_class and
  the SQLSTATE. The driver's message text is never logged or re-raised: it can
  include the server name and login, and it is not needed to diagnose the
  error classes above.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Sequence, Tuple

import pyodbc

from app.db.config import DatabaseConfig, build_connection_string

logger = logging.getLogger("stress_test_review.db")

_RETRYABLE_SQLSTATES = {"08001", "08S01", "HYT00", "HYT01"}
_ERROR_CLASSES = {
    "08001": "UpstreamUnavailable",
    "08S01": "UpstreamUnavailable",
    "HYT00": "TimeoutError",
    "HYT01": "TimeoutError",
    "28000": "AuthError",
    "IM002": "DriverNotFound",
    "01000": "DriverNotFound",  # unixODBC: "Can't open lib ..." when the driver file is missing
    "42000": "PermissionError",
}


class DatabaseConnectionError(Exception):
    def __init__(self, error_class: str, sqlstate: Optional[str], attempts: int) -> None:
        self.error_class = error_class
        self.sqlstate = sqlstate
        self.attempts = attempts
        super().__init__(f"{error_class} (SQLSTATE {sqlstate or 'unknown'}) after {attempts} attempt(s)")


def classify_error(exc: BaseException) -> Tuple[str, Optional[str]]:
    sqlstate = exc.args[0] if exc.args and isinstance(exc.args[0], str) else None
    message = " ".join(str(arg) for arg in exc.args[1:]).lower()
    if "certificate" in message:
        return "TlsCertificateError", sqlstate
    return _ERROR_CLASSES.get(sqlstate or "", "DatabaseError"), sqlstate


def connect_with_retry(
    config: DatabaseConfig,
    connect: Optional[Callable[..., Any]] = None,
    max_attempts: int = 3,
    backoff_s: Sequence[float] = (1.0, 2.0),
    sleep: Optional[Callable[[float], None]] = None,
) -> Any:
    connect = connect or pyodbc.connect
    sleep = sleep or time.sleep
    if max_attempts < 1 or not backoff_s:
        raise ValueError("max_attempts must be >= 1 and backoff_s must not be empty")
    connection_string = build_connection_string(config)  # holds the password: never log it

    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        try:
            conn = connect(connection_string, timeout=config.connect_timeout_s, readonly=True)
        except pyodbc.Error as exc:
            error_class, sqlstate = classify_error(exc)
            retryable = sqlstate in _RETRYABLE_SQLSTATES and error_class != "TlsCertificateError"
            _log(logging.WARNING, "db_connect_failed", attempt=attempt, max_attempts=max_attempts,
                 error_class=error_class, sqlstate=sqlstate, retryable=retryable,
                 duration_ms=_elapsed_ms(started), outcome="failure")
            if not retryable or attempt == max_attempts:
                raise DatabaseConnectionError(error_class, sqlstate, attempt) from None
            sleep(backoff_s[min(attempt - 1, len(backoff_s) - 1)])
        else:
            conn.timeout = config.query_timeout_s  # per-query timeout, seconds
            _log(logging.INFO, "db_connected", attempt=attempt, duration_ms=_elapsed_ms(started), outcome="success")
            return conn
    raise AssertionError("unreachable")  # loop always returns or raises


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _log(level: int, event: str, **context: Any) -> None:
    line = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": logging.getLevelName(level).lower(),
            "service": "backend", "event": event, **context}
    logger.log(level, json.dumps(line))
