"""Historical cases for the vector index (STORY-013), read from a history
extract's comments.csv (directives/ST-historical-comment-extraction.md).

A case is one review round in one thread (MessageId), comments ordered by
creation time:
  the LAST student ##Critique## comment since the previous reviewer answer,
  answered by the next reviewer comment marked ##FeedbackGiven## or ##Approved##.
Every round in a thread becomes a case, so a resubmission and its second
review are indexed too.

Same safeguards as the STORY-004 historical comparison
(evaluation/history_comparison.py):
- markers are read from the comment text, never from the extract's
  MarkerType column (SQL labels a comment by its FIRST marker, so a reviewer
  reply quoting "##Critique##" looks like a submission there);
- a critique carrying a reviewer marker is not a submission;
- a critique by the answering reviewer (a bare "##Critique##" a reviewer
  posted) is not the student's submission. Emails are compared in memory
  only and never kept.

case_id is the submission's CommentId (the idempotency key of the index).
Texts are plain text (HTML converted as for evaluation), review markers removed,
cut to the HistoricalCase caps. A round whose text is empty after that is
skipped and counted.
"""
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.basecamp.critique_marker_detector import classify_critique_marker, detect_review_markers
from app.evaluation.text import html_to_text
from app.models import HistoricalCase

MAX_TEXT = 2000
# Review markers such as ##Critique##, ##Please Critique##, ##FeedbackGiven##:
# workflow signals, not content, so they are removed from the indexed text.
# (evaluation.text.without_markers is different: it removes [SELECTED] and
# [image:] tags, which stay here because they are part of the submission.)
_REVIEW_MARKER = re.compile(r"##\s*[A-Za-z][A-Za-z ]{0,30}?\s*##")
_REVIEWER_MARKERS = {"FeedbackGiven", "Approved"}

Row = Dict[str, str]


def is_reviewer_answer(comment_html: str) -> bool:
    return bool(_REVIEWER_MARKERS & set(detect_review_markers(comment_html)))


def is_student_critique(comment_html: str) -> bool:
    return classify_critique_marker(comment_html) is not None and not is_reviewer_answer(comment_html)


def _plain(comment_html: str) -> str:
    return _REVIEW_MARKER.sub("", html_to_text(comment_html)).strip()


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def _author(row: Row) -> str:
    return (row.get("CreatorEmail") or "").strip().lower()


def _thread_rounds(thread: List[Row]) -> List[Tuple[Row, Row]]:
    rounds = []
    critique: Optional[Row] = None
    for row in sorted(thread, key=lambda r: (r["CommentCreatedDate"], int(r["CommentId"]))):
        if is_reviewer_answer(row["Comment"]):
            if critique is not None and _author(critique) != _author(row):
                rounds.append((critique, row))
            critique = None  # the next round starts after this answer
        elif is_student_critique(row["Comment"]):
            critique = row
    return rounds


def cases_from_rows(rows: List[Row]) -> Tuple[List[HistoricalCase], Counter]:
    """Returns (cases, skipped) where skipped counts rounds with no usable text."""
    threads: Dict[Tuple[str, str], List[Row]] = defaultdict(list)
    for row in rows:
        threads[(row["StressTest"], row["MessageId"])].append(row)
    cases: Dict[str, HistoricalCase] = {}
    skipped: Counter = Counter()
    for (stress_test, _message_id), thread in sorted(threads.items()):
        for critique, answer in _thread_rounds(thread):
            submission = _plain(critique["Comment"])
            feedback = _plain(answer["Comment"])
            if not submission or not feedback:
                skipped[f"ST{stress_test}"] += 1
                continue
            case_id = critique["CommentId"]
            cases[case_id] = HistoricalCase(case_id=case_id, stress_test_id=f"ST{stress_test}",
                                            submission_excerpt=_clip(submission), reviewer_feedback=_clip(feedback))
    return list(cases.values()), skipped


def load_cases_from_extract(extract_dir: Path) -> Tuple[List[HistoricalCase], Counter]:
    csv.field_size_limit(sys.maxsize)  # comment HTML can exceed csv's default field limit
    with open(extract_dir / "comments.csv", newline="", encoding="utf-8") as handle:
        return cases_from_rows(list(csv.DictReader(handle)))
