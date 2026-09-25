"""Feeds comments retrieved from the Basecamp API (STORY-002) into critique
intake (STORY-001, review_queue.intake.run_intake) without changing intake.

Why the ids line up: the Basecamp API's comment and message ids are the same
numbers stored in SQL Server's Basecamp_MessageBoards_MessageComments
(CommentId / MessageId, both Basecamp recording ids, ~1e9-1e10; checked
read-only on 2026-09-25). So a comment reaching intake from either source maps
to the same Review Queue item, and intake's per-comment_id idempotency holds.

The body passed to intake is the comment's Basecamp HTML, which is also what
the SQL table stores, so marker detection sees the same text either way.
"""
from typing import List

from app.basecamp.comment_source import CommentSource, RawCommentRow
from app.models import SubmissionDataset


class SubmissionCommentSource(CommentSource):
    """Already-retrieved data: no I/O, so the timeout has nothing to bound."""

    def __init__(self, dataset: SubmissionDataset) -> None:
        self._dataset = dataset

    def fetch_comments(self, timeout_s: float) -> List[RawCommentRow]:
        return [
            {
                "comment_id": comment.comment_id,
                "message_id": submission.message_id,
                "body": comment.content_html,
                "created_at": comment.created_at,
            }
            for submission in self._dataset.submissions
            for comment in submission.comments
        ]
