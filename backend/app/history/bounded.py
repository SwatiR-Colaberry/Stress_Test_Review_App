"""Bounded calls for historical retrieval (STORY-013): every call to the
vector index or the embedding model gets a per-attempt timeout and a capped
number of attempts, so retrieval can never hang a review.

Worst case per call: attempts x timeout_s plus the backoff between attempts.
Every failure is retried (the calls are local reads/writes and model runs,
where a retry is safe and idempotent); after the last attempt the caller's
error class is raised, naming the cause. Errors the caller marks as
permanent (no_retry) are raised at once.

A daemon thread runs each attempt (same pattern as the STORY-003 rule loader):
after a timeout the caller gets control back and the process can still exit.
A timed-out attempt may still finish in the background; its result is dropped.
"""
import threading
import time
from typing import Any, Callable, Dict, Tuple, Type, TypeVar

T = TypeVar("T")


def bounded_call(
    fn: Callable[[], T],
    *,
    what: str,
    error: Type[Exception],
    timeout_s: float,
    attempts: int,
    backoff_s: float = 0.5,
    no_retry: Tuple[Type[Exception], ...] = (),
) -> T:
    """Runs fn with a timeout per attempt. An exception of a no_retry type is
    permanent (retrying cannot help) and is re-raised at once, unchanged."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    cause = "no attempt made"
    for attempt in range(1, attempts + 1):
        outcome: Dict[str, Any] = {}

        def run() -> None:
            try:
                outcome["value"] = fn()
            except Exception as exc:  # noqa: BLE001 — thread boundary: handed back and classified below
                outcome["error"] = exc

        worker = threading.Thread(target=run, name=f"bounded-{what}", daemon=True)
        worker.start()
        worker.join(timeout_s)
        if worker.is_alive():
            cause = f"timed out after {timeout_s:g}s"
        elif isinstance(outcome.get("error"), no_retry):
            raise outcome["error"]
        elif "error" in outcome:
            cause = type(outcome["error"]).__name__
        else:
            return outcome["value"]
        if attempt < attempts:
            time.sleep(backoff_s * attempt)
    raise error(f"{what} failed after {attempts} attempts: {cause}")
