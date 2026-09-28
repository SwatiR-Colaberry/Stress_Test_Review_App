"""Evaluation input check (STORY-004: REQ-005).

Runs BEFORE any Claude call. A submission that is incomplete, or has no
loaded rules to be judged against, is rejected with a reason code instead of
being sent to Claude and paid for:

  reason_code           when
  COMMENT_NOT_FOUND     the critiqued comment is not in the retrieved submission
  NOT_A_SUBMISSION      the comment carries ##FeedbackGiven## / ##Approved##: it
                        is a reviewer's comment (quoting "##Critique##"), not
                        the student's work (13 of 553 in the history extract)
  SUBMISSION_EMPTY      the comment has no text of the student's own once
                        HTML and markers are removed (e.g. only a screenshot)
  SUBMISSION_TOO_LARGE  the comment HTML is over MAX_SUBMISSION_CHARS; it is
                        rejected, never silently truncated (a cheap guard;
                        the token count is checked again before sending)
  RULES_NOT_LOADED      rule loading went to manual resolution (STORY-003)

The HTML is converted to plain text (app.evaluation.text), keeping the yellow
highlight as [SELECTED] and embedded files as [image: ...] / [file: ...].
Links and attachments are always read from the comment HTML itself (the
STORY-002 extractor), so they do not depend on who built the Submission.
"""
from typing import List, Literal

from pydantic import BaseModel

from app.models import BasecampId, Submission, SubmissionAttachment, SubmissionLink
from app.basecamp.content_extractor import extract_attachments_and_links
from app.basecamp.critique_marker_detector import detect_review_markers
from app.evaluation.text import html_to_text, without_markers
from app.rules.loader import RuleLoadResult
from app.rules.module import RuleModule

# Bounds the cost of one call. The largest ST0 ##Critique## comment in the
# 2026-09-25 per-Stress-Test extract (45 comments) is 25,064 characters of HTML.
MAX_SUBMISSION_CHARS = 100_000

InputReasonCode = Literal[
    "COMMENT_NOT_FOUND", "NOT_A_SUBMISSION", "SUBMISSION_EMPTY", "SUBMISSION_TOO_LARGE", "RULES_NOT_LOADED"
]


class SubmissionIncompleteError(Exception):
    """The submission cannot be evaluated. reason_code says why."""
    error_class = "ValidationError"

    def __init__(self, reason_code: InputReasonCode, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class EvaluationInput(BaseModel):
    """Everything one evaluation needs, already checked."""
    comment_id: BasecampId
    message_id: BasecampId
    title: str
    content_text: str  # plain text with [SELECTED] / [image: ...] / [file: ...] markers
    attachments: List[SubmissionAttachment] = []
    links: List[SubmissionLink] = []
    module: RuleModule


def prepare_evaluation_input(submission: Submission, comment_id: int, rules: RuleLoadResult) -> EvaluationInput:
    """Return the checked input for evaluating one critiqued comment, or raise
    SubmissionIncompleteError. Pure: no I/O, safe to call any number of times."""
    if rules.outcome != "loaded" or rules.module is None:
        raise SubmissionIncompleteError(
            "RULES_NOT_LOADED", f"no rule module loaded (reason: {rules.reason_code})"
        )
    comment = next((c for c in submission.comments if c.comment_id == comment_id), None)
    if comment is None:
        raise SubmissionIncompleteError(
            "COMMENT_NOT_FOUND", f"comment {comment_id} is not in submission {submission.message_id}"
        )
    if {"FeedbackGiven", "Approved"} & set(detect_review_markers(comment.content_html)):
        raise SubmissionIncompleteError(
            "NOT_A_SUBMISSION", f"comment {comment_id} is reviewer feedback, not a student submission"
        )
    if len(comment.content_html) > MAX_SUBMISSION_CHARS:
        raise SubmissionIncompleteError(
            "SUBMISSION_TOO_LARGE",
            f"comment {comment_id} is {len(comment.content_html)} characters (limit {MAX_SUBMISSION_CHARS})",
        )
    text = html_to_text(comment.content_html)
    if not without_markers(text):
        raise SubmissionIncompleteError("SUBMISSION_EMPTY", f"comment {comment_id} has no text")
    attachments, links = extract_attachments_and_links(comment.content_html)
    return EvaluationInput(
        comment_id=comment.comment_id,
        message_id=submission.message_id,
        title=submission.title,
        content_text=text,
        attachments=attachments,
        links=links,
        module=rules.module,
    )
