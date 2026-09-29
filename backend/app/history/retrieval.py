"""Similar past reviews for a submission (REQ-019, STORY-013).

retrieve_similar_cases() always returns a HistoryRetrieval and never fails
the review it serves:
- found:       the top k cases from the same Stress Test, most similar first;
- none_found:  an empty list and a message saying so (nothing indexed for
               this Stress Test, or no submission text to compare);
- unavailable: the embedding model or the vector index could not be used
               (after their bounded retries), or the index broke the
               same-Stress-Test contract. The list is empty; message and
               error_class tell the reviewer, and the review goes on without
               historical examples.

Historical cases are examples only. Every message says the current Stress
Test rules decide; the evaluator keeps the rules as the only source of what
passes or fails (see evaluation/prompt.py).

One JSON log line per retrieval (outcome, status, count, duration, error
class). Student text never goes into the log.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, List

from app.history.embedder import Embedder, EmbeddingError
from app.history.vector_index import VectorIndex, VectorIndexError, check_k
from app.models import HistoryRetrieval, SimilarCase

logger = logging.getLogger("stress_test_review.history")

CONTRACT_VIOLATION = "ContractViolation"


def retrieve_similar_cases(
    stress_test_id: str,
    submission_text: str,
    *,
    index: VectorIndex,
    embedder: Embedder,
    k: int,
    correlation_id: str,
) -> HistoryRetrieval:
    check_k(k)  # a bad k is a programming/config error, not an outage
    started = time.monotonic()
    if not submission_text.strip():
        result = _none_found(stress_test_id, "there is no submission text to compare")
    else:
        result = _search(stress_test_id, submission_text, index, embedder, k)
    _log(result, k, correlation_id, started)
    return result


def _search(stress_test_id: str, text: str, index: VectorIndex, embedder: Embedder, k: int) -> HistoryRetrieval:
    try:
        vector = embedder.embed([text])[0]
        cases = index.search(stress_test_id, vector, k)
    except (EmbeddingError, VectorIndexError) as exc:
        return _unavailable(stress_test_id, exc.error_class, str(exc))
    foreign = sorted({case.stress_test_id for case in cases} - {stress_test_id})
    if foreign:
        # Never filter silently: an index that leaks another Stress Test is broken.
        return _unavailable(stress_test_id, CONTRACT_VIOLATION,
                            f"the index returned cases from {', '.join(foreign)}")
    if not cases:
        return _none_found(stress_test_id, f"no past reviews are indexed for {stress_test_id}")
    return _found(stress_test_id, cases)


def _found(stress_test_id: str, cases: List[SimilarCase]) -> HistoryRetrieval:
    return HistoryRetrieval(
        stress_test_id=stress_test_id, status="found", cases=cases,
        message=f"{len(cases)} similar past review(s) from {stress_test_id}, shown as examples only; "
                f"the current {stress_test_id} rules decide.",
    )


def _none_found(stress_test_id: str, why: str) -> HistoryRetrieval:
    return HistoryRetrieval(
        stress_test_id=stress_test_id, status="none_found", cases=[],
        message=f"No similar past reviews: {why}. The evaluation uses the {stress_test_id} rules only.",
    )


def _unavailable(stress_test_id: str, error_class: str, cause: str) -> HistoryRetrieval:
    head = "Historical examples are unavailable ("
    tail = "); this review continues without them."
    room = 300 - len(head) - len(tail)
    cause = cause if len(cause) <= room else cause[: room - 1] + "…"
    return HistoryRetrieval(stress_test_id=stress_test_id, status="unavailable", cases=[],
                            message=f"{head}{cause}{tail}", error_class=error_class)


def _log(result: HistoryRetrieval, k: int, correlation_id: str, started: float) -> None:
    line: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": "warn" if result.status == "unavailable" else "info",
        "service": "backend",
        "event": "history_retrieval",
        "correlation_id": correlation_id,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "outcome": "failure" if result.status == "unavailable" else "success",
        "context": {"stress_test_id": result.stress_test_id, "status": result.status,
                    "cases": len(result.cases), "k": k},
    }
    if result.error_class:
        line["error_class"] = result.error_class
    logger.log(logging.WARNING if result.status == "unavailable" else logging.INFO, json.dumps(line))
