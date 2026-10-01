"""Sends this app's structured JSON log lines to stdout (CLAUDE.md
Observability: JSON to stdout, captured by the container runtime).

Without this, Python's default leaves app loggers at WARNING with no handler,
so INFO events such as critique_marker_detected are silently dropped when the
app runs under uvicorn. Safe to call more than once: it never adds a second
handler or filter.

It also redacts secret-bearing query values (the one-time Basecamp sign-in
`code` and `state`, any `*token*`) from uvicorn's access log, which otherwise
prints every request URL in full (STORY-014: no token in logs).
"""
import logging
import re
import sys

APP_LOGGER_NAME = "stress_test_review"
_HANDLER_NAME = "stress_test_review_stdout"
_SECRET_PARAM = re.compile(r"([?&](?:code|state|[a-z_]*token)=)[^&#\s]*", re.IGNORECASE)


def redact_query(path: str) -> str:
    return _SECRET_PARAM.sub(r"\1<redacted>", path)


class _RedactAccessLog(logging.Filter):
    """Uvicorn access records carry (client, method, path, http_version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (args[0], args[1], redact_query(args[2]), args[3], args[4])
        return True


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(level)
    if not any(h.get_name() == _HANDLER_NAME for h in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))  # messages are already JSON
        logger.addHandler(handler)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _RedactAccessLog) for f in access.filters):
        access.addFilter(_RedactAccessLog())
    return logger
