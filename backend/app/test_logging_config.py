import io
import json
import logging

from app.logging_config import configure_logging
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
        process_comment(row, InMemoryReviewQueueStore())
    finally:
        handler.setStream(original)
    [line] = [json.loads(text) for text in buffer.getvalue().splitlines()]
    assert (line["event"], line["comment_id"]) == ("critique_marker_detected", 5550001)
