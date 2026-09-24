"""Sends this app's structured JSON log lines to stdout (CLAUDE.md
Observability: JSON to stdout, captured by the container runtime).

Without this, Python's default leaves app loggers at WARNING with no handler,
so INFO events such as critique_marker_detected are silently dropped when the
app runs under uvicorn. Safe to call more than once: it never adds a second
handler.
"""
import logging
import sys

APP_LOGGER_NAME = "stress_test_review"
_HANDLER_NAME = "stress_test_review_stdout"


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(level)
    if not any(h.get_name() == _HANDLER_NAME for h in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))  # messages are already JSON
        logger.addHandler(handler)
    return logger
