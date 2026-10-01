import io
import json
import logging

from app.logging_config import configure_logging
from app.audit.trail import InMemoryAuditTrail
from app.review_queue.intake import process_comment
from app.review_queue.store import InMemoryReviewQueueStore


def test_configuring_twice_installs_exactly_one_handler_at_info():
    logger = configure_logging()
    configure_logging()
    ours = [h for h in logger.handlers if h.get_name() == "stress_test_review_stdout"]
    assert len(ours) == 1
    assert logging.getLogger("stress_test_review.intake").isEnabledFor(logging.INFO)


def test_detection_event_reaches_the_configured_handler_with_the_comment_id():
    logger = configure_logging()
    [handler] = [h for h in logger.handlers if h.get_name() == "stress_test_review_stdout"]
    buffer = io.StringIO()
    original = handler.setStream(buffer)
    try:
        row = {"comment_id": 5550001, "message_id": 9, "body": "##Critique##", "created_at": "2026-09-24T12:00:00Z"}
        process_comment(row, InMemoryReviewQueueStore(), InMemoryAuditTrail())
    finally:
        handler.setStream(original)
    [line] = [json.loads(text) for text in buffer.getvalue().splitlines()]
    assert (line["event"], line["comment_id"]) == ("critique_marker_detected", 5550001)


def _access_line(path: str) -> str:
    """Formats one uvicorn access-log record the way uvicorn does, after our filters."""
    configure_logging()
    logger = logging.getLogger("uvicorn.access")
    record = logger.makeRecord("uvicorn.access", logging.INFO, __file__, 0,
                               '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", path, "1.1", 303), None)
    assert all(f.filter(record) for f in logger.filters)
    return record.getMessage()


def test_the_access_log_never_shows_the_basecamp_sign_in_code_or_state():
    line = _access_line("/auth/callback?code=SECRETCODE123&state=STATEVALUE456")
    assert "SECRETCODE123" not in line and "STATEVALUE456" not in line
    assert "/auth/callback?code=<redacted>&state=<redacted>" in line


def test_the_access_log_redacts_token_like_parameters_but_keeps_ordinary_ones():
    line = _access_line("/x?next=%2Fqueue%2F&access_token=T0K&refresh_token=R3F&review=abc")
    assert "T0K" not in line and "R3F" not in line
    assert "next=%2Fqueue%2F" in line and "review=abc" in line


def test_the_access_log_leaves_paths_without_a_query_alone_and_filters_once():
    configure_logging()
    configure_logging()
    assert len(logging.getLogger("uvicorn.access").filters) == 1
    assert _access_line("/queue/") .endswith('"GET /queue/ HTTP/1.1" 303')
