"""One JSON log line per sign-in event (CLAUDE.md Observability). Callers pass
codes and error classes only: never an email, token, code or secret."""
import json
import logging
from datetime import datetime, timezone

from app.logging_config import APP_LOGGER_NAME

logger = logging.getLogger(APP_LOGGER_NAME)


def log_event(event: str, correlation_id: str, level: int = logging.INFO, **context) -> None:
    logger.log(level, json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(), "level": logging.getLevelName(level).lower(),
        "service": "backend", "event": event, "correlation_id": correlation_id,
        "outcome": "failure" if level >= logging.WARNING else "success", **context,
    }))
