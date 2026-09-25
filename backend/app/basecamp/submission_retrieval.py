"""Retrieves everything a reviewer needs from one Basecamp project (REQ-004).

A submission is one message on the project's message board. For each one we
return its body, its comments, and the attachments and links found in both
(content_extractor.py).

API calls (Basecamp 3/4, via BasecampClient, OAuth 2.0 per REQ-012):
  GET /projects/{project}.json                                  -> find the message board in the dock
  GET /buckets/{project}/message_boards/{board}/messages.json   -> all messages (paginated)
  GET /buckets/{project}/recordings/{message}/comments.json     -> all comments per message (paginated;
                                                                   skipped when comments_count is 0)

A project whose message board is disabled or empty returns an empty dataset.

Audit (trust criterion): every retrieval logs submission_retrieval_started and
then _completed or _failed (including on unexpected errors), each with a timestamp, the requesting user id, the
project id and a correlation id. On failure the error is logged and re-raised;
no partial dataset is ever returned.

Audit trail (STORY-011): the same three moments are also recorded in the
append-only audit trail (retrieval_started / _completed / _failed, actor = the
requesting user). "started" is recorded before any Basecamp call and
"completed" before the dataset is returned; if either cannot be written,
AuditWriteError is raised and no data is returned (retrieval is read-only, so
a re-run is safe). If "failed" cannot be written, the original error is still
raised so its cause is not hidden, and audit_write_failed is logged. Retries and timeouts live in the client.
Read-only: running it twice changes nothing in Basecamp.
"""
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from app.audit.trail import AuditTrail, AuditWriteError
from app.basecamp.api_client import BasecampClient, BasecampError, BasecampResponseError
from app.basecamp.content_extractor import extract_attachments_and_links
from app.models import MAX_ID_LENGTH, AuditEvent, BasecampId, Submission, SubmissionComment, SubmissionDataset

logger = logging.getLogger("stress_test_review.submission_retrieval")


def retrieve_project_submissions(
    client: BasecampClient,
    project_id: int,
    requested_by_user_id: str,
    *,
    audit: AuditTrail,
    correlation_id: Optional[str] = None,
) -> SubmissionDataset:
    if not isinstance(project_id, int) or isinstance(project_id, bool) or project_id <= 0:
        raise ValueError("project_id must be a positive integer")
    if not isinstance(requested_by_user_id, str) or not requested_by_user_id.strip():
        raise ValueError("requested_by_user_id is required for the audit log")
    if len(requested_by_user_id) > MAX_ID_LENGTH:
        raise ValueError(f"requested_by_user_id is longer than {MAX_ID_LENGTH} characters")
    correlation_id = correlation_id or str(uuid.uuid4())
    context = {"project_id": project_id, "requested_by_user_id": requested_by_user_id,
               "correlation_id": correlation_id}
    started = time.monotonic()
    _record(audit, "retrieval_started", "success", context)
    _log(logging.INFO, "submission_retrieval_started", **context)
    try:
        submissions = _fetch_submissions(client, project_id)
    except BasecampError as exc:
        _log(logging.ERROR, "submission_retrieval_failed", **context, outcome="failure",
             error_class=exc.error_class, status=exc.status_code, duration_ms=_elapsed_ms(started))
        _record_failure(audit, exc.error_class, context)
        raise
    except Exception as exc:
        # Not an expected Basecamp failure (a bug, or an HTTP-layer error the
        # client does not classify). Still close the audit trail, then re-raise.
        _log(logging.ERROR, "submission_retrieval_failed", **context, outcome="failure",
             error_class="UnexpectedError", cause=type(exc).__name__, duration_ms=_elapsed_ms(started))
        _record_failure(audit, "UnexpectedError", context)
        raise
    _record(audit, "retrieval_completed", "success", context)
    _log(logging.INFO, "submission_retrieval_completed", **context, outcome="success",
         submission_count=len(submissions),
         comment_count=sum(len(s.comments) for s in submissions),
         attachment_count=sum(len(s.attachments) + sum(len(c.attachments) for c in s.comments) for s in submissions),
         link_count=sum(len(s.links) + sum(len(c.links) for c in s.comments) for s in submissions),
         duration_ms=_elapsed_ms(started))
    return SubmissionDataset(project_id=project_id, requested_by_user_id=requested_by_user_id,
                             retrieved_at=datetime.now(timezone.utc), submissions=submissions)


def _fetch_submissions(client: BasecampClient, project_id: int) -> List[Submission]:
    project = client.get_json(f"/projects/{project_id}.json")
    board_id = _message_board_id(project)
    if board_id is None:
        return []
    messages = client.get_all(f"/buckets/{project_id}/message_boards/{board_id}/messages.json")
    submissions = []
    for raw_message in messages:
        message = _parse(_RawRecording, raw_message, "message")
        raw_comments = [] if message.comments_count == 0 else client.get_all(
            f"/buckets/{project_id}/recordings/{message.id}/comments.json")
        comments = [_to_comment(_parse(_RawRecording, raw, "comment")) for raw in raw_comments]
        attachments, links = extract_attachments_and_links(message.content)
        submissions.append(Submission(
            message_id=message.id, title=message.subject or message.title or "",
            author_id=message.author_id, created_at=message.created_at,
            content_html=message.content or "", attachments=attachments, links=links, comments=comments,
        ))
    return submissions


def _message_board_id(project: Any) -> Optional[int]:
    """The enabled message board in the project's dock, or None if there is none."""
    if not isinstance(project, dict) or not isinstance(project.get("dock"), list):
        raise BasecampResponseError("Project response has no dock list")
    for tool in project["dock"]:
        if isinstance(tool, dict) and tool.get("name") == "message_board" and tool.get("enabled", True):
            board_id = tool.get("id")
            if not isinstance(board_id, int) or isinstance(board_id, bool) or board_id <= 0:
                raise BasecampResponseError("Message board in dock has no valid id")
            return board_id
    return None


class _RawRecording(BaseModel):
    """The fields we use from a Basecamp message or comment; others are ignored."""
    model_config = ConfigDict(extra="ignore")

    id: BasecampId
    created_at: datetime
    content: Optional[str] = None
    subject: Optional[str] = None
    title: Optional[str] = None
    creator: Optional[Dict[str, Any]] = None
    comments_count: Optional[int] = None  # messages only; 0 lets us skip the comments call

    @property
    def author_id(self) -> Optional[int]:
        value = (self.creator or {}).get("id")
        return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse(model: type, raw: Any, kind: str) -> Any:
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        # Field names only; pydantic's message would echo submission content.
        fields = sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})
        raise BasecampResponseError(f"Malformed Basecamp {kind}: {', '.join(fields) or 'not an object'}") from None


def _to_comment(raw: _RawRecording) -> SubmissionComment:
    attachments, links = extract_attachments_and_links(raw.content)
    return SubmissionComment(comment_id=raw.id, author_id=raw.author_id, created_at=raw.created_at,
                             content_html=raw.content or "", attachments=attachments, links=links)


def _record(audit: AuditTrail, action: str, outcome: str, context: Dict[str, Any],
            reason_code: Optional[str] = None) -> None:
    event = AuditEvent(
        event_id=str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc),
        action=action,
        actor_id=context["requested_by_user_id"],
        outcome=outcome,
        correlation_id=context["correlation_id"],
        project_id=context["project_id"],
        reason_code=reason_code,
    )
    try:
        audit.record(event)
    except AuditWriteError:
        _log(logging.ERROR, "audit_write_failed", **context, audit_action=action, outcome="failure",
             error_class=AuditWriteError.error_class)
        raise


def _record_failure(audit: AuditTrail, error_class: str, context: Dict[str, Any]) -> None:
    """Records retrieval_failed. If that write fails too, the caller's original
    error is what surfaces (audit_write_failed is already logged by _record)."""
    try:
        _record(audit, "retrieval_failed", "failure", context, reason_code=error_class)
    except AuditWriteError:
        pass  # logged in _record; the Basecamp error being re-raised is the real cause


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
