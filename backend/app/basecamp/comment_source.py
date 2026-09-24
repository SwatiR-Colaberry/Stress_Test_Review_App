"""Where raw Basecamp comment rows come from (Master Spec §5: the primary
source is SQL Server's Basecamp_MessageBoards_MessageComments).

Only a fixture source exists today. The real SQL Server adapter needs
credentials and a driver dependency that have not been approved yet (decision
logged in PROGRESS.md, session CC-20260924-e18o); it will implement
CommentSource and must honor the timeout it is given.

Failure handling (fetch_with_retry):
- Retries only on CommentSourceUnavailable, TimeoutError and ConnectionError.
- At most max_attempts attempts (default 3), fixed backoff schedule between them.
- When attempts are exhausted it raises CommentSourceUnavailable, so the caller
  surfaces a visible error. Nothing is written in that case.
- Any other exception is a bug or a contract problem, not a transient outage,
  and is raised immediately without retrying.
"""
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("stress_test_review.comment_source")

RawCommentRow = Dict[str, Any]

_RETRYABLE = (TimeoutError, ConnectionError)


class CommentSourceUnavailable(Exception):
    """The comment source could not be reached (after retries, when raised by fetch_with_retry)."""


class CommentSource(ABC):
    @abstractmethod
    def fetch_comments(self, timeout_s: float) -> List[RawCommentRow]:
        """Returns raw comment rows. Must give up after timeout_s seconds."""


class FixtureCommentSource(CommentSource):
    """Canned rows for tests and local demos. NOT a live SQL Server connection."""

    def __init__(self, rows: Sequence[RawCommentRow]) -> None:
        self._rows = [dict(row) for row in rows]

    def fetch_comments(self, timeout_s: float) -> List[RawCommentRow]:
        return [dict(row) for row in self._rows]


def fetch_with_retry(
    source: CommentSource,
    max_attempts: int = 3,
    timeout_s: float = 10.0,
    backoff_s: Sequence[float] = (0.5, 1.0, 2.0),
    sleep: Optional[Callable[[float], None]] = None,
) -> List[RawCommentRow]:
    sleep = sleep or time.sleep  # resolved per call so tests can patch it
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if not backoff_s:
        raise ValueError("backoff_s must contain at least one delay")
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        try:
            rows = source.fetch_comments(timeout_s=timeout_s)
        except (CommentSourceUnavailable, *_RETRYABLE) as exc:
            _log(
                logging.WARNING,
                "comment_fetch_failed",
                attempt=attempt,
                max_attempts=max_attempts,
                error_class=type(exc).__name__,
                duration_ms=_elapsed_ms(started),
                outcome="failure",
            )
            if attempt == max_attempts:
                raise CommentSourceUnavailable(
                    f"Comment source unreachable after {max_attempts} attempts ({type(exc).__name__})"
                ) from exc
            sleep(backoff_s[min(attempt - 1, len(backoff_s) - 1)])
        else:
            _log(
                logging.INFO,
                "comment_fetch_succeeded",
                attempt=attempt,
                row_count=len(rows),
                duration_ms=_elapsed_ms(started),
                outcome="success",
            )
            return rows
    raise AssertionError("unreachable")  # loop always returns or raises


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _log(level: int, event: str, **context: Any) -> None:
    line = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": logging.getLevelName(level).lower(),
        "service": "backend",
        "event": event,
        **context,
    }
    logger.log(level, json.dumps(line))
