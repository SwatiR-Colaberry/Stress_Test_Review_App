"""Read a Basecamp thread around the comment being reviewed (STORY-004,
thread history H1). Pure: no I/O, no Claude, same answer every time.

One Stress Test is one thread: the message, then comments in date order
(critique requests, reviewer feedback, resubmissions, chat). For the
##Critique## comment being reviewed, read_thread() works out:

- parts: what the student has submitted since the reviewer last answered.
  Walking back from the reviewed comment, the same student's earlier comments
  (marked or not) are parts of this submission, until a reviewer's
  ##FeedbackGiven## / ##Approved## comment is reached. Students often split
  one submission over several comments ("Critique, Critique, FeedbackGiven":
  4 of the 15 ST0 cases in the 2026-09-25 comparison). If the walk reaches
  the start of the thread, the message itself is a part when the student
  wrote it. Comments by anyone else are skipped (a reviewer's chat is not
  the student's work).
- previous_feedback: that reviewer comment, i.e. what the student was asked
  to fix last time. None for a first submission.
- version: 1 + the number of reviewer feedback comments before the reviewed
  comment (1 = first submission, 2 = after one round of feedback, ...).

Markers decide who is a reviewer: in the history extract 83 of 90 threads
have reviewers distinct from the student, but 13 have several critique
authors, so author ids are only used to tell the student's own unmarked
comments from other people's. When an author id is missing, only
##Critique##-marked comments count as the student's.

Nothing is cut: every part is returned in full. The size limit is enforced
where the text is sent (input check, count_tokens), which routes an
oversized thread to manual resolution instead of truncating it.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.basecamp.critique_marker_detector import classify_critique_marker, detect_review_markers
from app.evaluation.text import html_to_text
from app.models import BasecampId, Submission, SubmissionComment

_REVIEWER_MARKERS = {"FeedbackGiven", "Approved"}


class ThreadPart(BaseModel):
    comment_id: Optional[int] = None  # None: the thread's message itself
    created_at: datetime
    content_html: str


class PreviousFeedback(BaseModel):
    comment_id: int
    created_at: datetime
    text: str  # plain text of the reviewer's comment


class ThreadContext(BaseModel):
    comment_id: BasecampId  # the reviewed comment
    message_id: BasecampId
    version: int = Field(ge=1)
    parts: List[ThreadPart] = Field(min_length=1)  # oldest first; the last is the reviewed comment
    previous_feedback: Optional[PreviousFeedback] = None

    @property
    def is_split(self) -> bool:
        return len(self.parts) > 1


class CommentNotInThreadError(Exception):
    error_class = "ValidationError"


def is_reviewer_feedback(comment: SubmissionComment) -> bool:
    return bool(_REVIEWER_MARKERS & set(detect_review_markers(comment.content_html)))


def _is_students(comment: SubmissionComment, student_id: Optional[int]) -> bool:
    if student_id is not None and comment.author_id is not None:
        return comment.author_id == student_id
    return classify_critique_marker(comment.content_html) is not None


def read_thread(submission: Submission, comment_id: int) -> ThreadContext:
    comments = sorted(submission.comments, key=lambda c: (c.created_at, c.comment_id))
    index = next((i for i, c in enumerate(comments) if c.comment_id == comment_id), None)
    if index is None:
        raise CommentNotInThreadError(f"comment {comment_id} is not in thread {submission.message_id}")
    reviewed = comments[index]
    student_id = reviewed.author_id

    parts = [ThreadPart(comment_id=reviewed.comment_id, created_at=reviewed.created_at,
                        content_html=reviewed.content_html)]
    previous: Optional[PreviousFeedback] = None
    for earlier in reversed(comments[:index]):
        if is_reviewer_feedback(earlier):
            previous = PreviousFeedback(comment_id=earlier.comment_id, created_at=earlier.created_at,
                                        text=html_to_text(earlier.content_html))
            break
        if _is_students(earlier, student_id):
            parts.insert(0, ThreadPart(comment_id=earlier.comment_id, created_at=earlier.created_at,
                                       content_html=earlier.content_html))
    else:  # reached the start of the thread without reviewer feedback
        if submission.content_html.strip() and student_id is not None and submission.author_id == student_id:
            parts.insert(0, ThreadPart(created_at=submission.created_at, content_html=submission.content_html))

    rounds = sum(1 for earlier in comments[:index] if is_reviewer_feedback(earlier))
    return ThreadContext(comment_id=reviewed.comment_id, message_id=submission.message_id, version=rounds + 1,
                         parts=parts, previous_feedback=previous)
