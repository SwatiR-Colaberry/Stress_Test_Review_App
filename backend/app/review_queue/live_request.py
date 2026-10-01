"""Turns one real Stress Test thread, read from SQL Server, into what the app
needs to review its newest request: the comment for intake and the
submission for the AI evaluation. Pure: no database, no network.

Used by backend/scripts/live_trial.py with the rows of
app/basecamp/sql/st0_newest_request.sql. The request is the LAST comment that
carries a ##Critique## marker and no reviewer marker (FeedbackGiven /
Approved), so a reviewer's feedback that quotes "##Critique##" is never taken
for it. The submission holds the thread up to and including that request.

Emails are only turned into in-memory author numbers (to tell the student's
comments from others') and never kept. The author's display name goes to the
queue item, which shows it to signed-in reviewers only.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.basecamp.content_extractor import extract_attachments_and_links
from app.basecamp.critique_marker_detector import classify_critique_marker, detect_review_markers
from app.models import BASECAMP_URL_PATTERN, BasecampComment, Submission, SubmissionComment

REVIEWER_MARKERS = {"FeedbackGiven", "Approved"}


class NoRequestFound(Exception):
    """The thread has no student ##Critique## request."""


class LiveRequest(BaseModel):
    comment: BasecampComment  # for intake
    submission: Submission  # for the evaluation
    step_name: str  # e.g. "Stress Test 0 - ...": picks the rule module
    project_bcp_id: str
    later_comments: int  # comments after the request (e.g. feedback already given)


def is_student_request(body: str) -> bool:
    return classify_critique_marker(body) is not None and not set(detect_review_markers(body)) & REVIEWER_MARKERS


def newest_request(rows: List[Dict[str, Any]]) -> LiveRequest:
    """rows: one thread's comments, any order, with the query's column names."""
    thread = sorted(rows, key=lambda row: (parse_time(row["CommentCreatedDate"]), int(row["CommentId"])))
    at = next((i for i in range(len(thread) - 1, -1, -1) if is_student_request(thread[i]["Comment"] or "")), None)
    if at is None:
        raise NoRequestFound("no student ##Critique## comment in this thread")
    request, visible = thread[at], thread[: at + 1]

    authors: Dict[str, int] = {}
    comments = []
    for row in visible:
        attachments, links = extract_attachments_and_links(row["Comment"] or "")
        comments.append(SubmissionComment(
            comment_id=int(row["CommentId"]), created_at=parse_time(row["CommentCreatedDate"]),
            author_id=authors.setdefault((row.get("CreatorEmail") or "").lower(), len(authors) + 1),
            content_html=row["Comment"] or "", attachments=attachments, links=links,
        ))
    comment = BasecampComment(
        comment_id=int(request["CommentId"]), message_id=int(request["MessageId"]), body=request["Comment"],
        created_at=parse_time(request["CommentCreatedDate"]), author_name=_name(request.get("CreatorName")),
        app_url=_url(request.get("MessageBoardURL")), project_id=_bucket(request.get("MessageBoardURL")),
    )
    submission = Submission(message_id=comment.message_id, title=request["StepName"],
                            created_at=comments[0].created_at, content_html="", comments=comments)
    return LiveRequest(comment=comment, submission=submission, step_name=request["StepName"],
                       project_bcp_id=str(request["BCP_ID"]), later_comments=len(thread) - at - 1)


def parse_time(value: Any) -> datetime:
    """SQL Server gives naive datetimes (or strings in tests); both are read as UTC."""
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace(" ", "T")[:26])
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _name(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return value[:200] or None


def _bucket(url: Optional[str]) -> Optional[int]:
    """The Basecamp project (bucket) id in a Basecamp link: needed to read the comment's images."""
    found = re.search(r"/buckets/(\d{1,18})/", _url(url) or "")
    return int(found.group(1)) if found else None


def _url(value: Optional[str]) -> Optional[str]:
    """Only a well-formed Basecamp https link is kept; anything else is dropped."""
    value = (value or "").strip()
    if not value or len(value) > 500 or not re.match(BASECAMP_URL_PATTERN, value):
        return None
    return value

