"""Historical comparison of AI drafts against human ST0 feedback (STORY-004).

Pure helpers for backend/scripts/compare_st0_history.py: pick the cases from
a history extract, estimate the cost before any paid call, and write the
side-by-side report.

A case, per ST0 thread: the FIRST human ##FeedbackGiven## comment, and the
LAST student ##Critique## comment before it (one without a reviewer marker,
not written by that feedback's author: reviewers sometimes post a bare
"##Critique##" themselves) (the version that reviewer answered).
The case's Submission holds the thread's comments up to and including that
critique - never the feedback that answers it, so Claude cannot see the
answer key. Only the comment HTML is used; the email column is turned into
an in-memory author number (to tell the student's comments from others')
and never kept.

Prices: Claude Sonnet 5 first-party rates from the Claude API reference
(cached 2026-06-24) - check current pricing before relying on a figure.
"""
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel

from app.basecamp.content_extractor import extract_attachments_and_links
from app.basecamp.critique_marker_detector import classify_critique_marker, detect_review_markers
from app.evaluation.text import html_to_text
from app.models import EvaluationResult, Submission, SubmissionComment

# USD per 1M tokens, claude-sonnet-5
PRICE_INPUT = 2.00
PRICE_OUTPUT = 10.00
PRICE_CACHE_WRITE = 2.50  # 5-minute cache write, 1.25 x input
PRICE_CACHE_READ = 0.20  # 0.1 x input
EXPECTED_OUTPUT_TOKENS = 600  # per stage call at low effort; an assumption, measured by the paid run

# Words a human reviewer uses when raising each ST0 rule. A HINT for the
# report only (the reviewer's text is shown next to it); never a verdict.
RULE_HINTS: Dict[str, str] = {
    "ST0-001": r"descri",
    "ST0-002": r"\blink|source|url",
    "ST0-003": r"collect|compil|gather|how the data",
    "ST0-004": r"screenshot|preview|header|rows",
    "ST0-005": r"upload|attach|dataset file|csv|excel",
    "ST0-006": r"\b(?:8|10|eight|ten)\b|more problems|fewer problems|number of problems",
    "ST0-007": r"missing|dependent|independent|target audience|future capab|algorithm|model type",
    "ST0-008": r"select|highlight|chosen|choose",
}


@dataclass(frozen=True)
class Case:
    project_id: str
    step_name: str
    submission: Submission
    comment_id: int
    human_feedback_text: str


def load_cases(csv_path: Path, stress_test: str = "0") -> List[Case]:
    csv.field_size_limit(sys.maxsize)
    with open(csv_path, newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["StressTest"] == stress_test]
    threads: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        threads[row["MessageId"]].append(row)

    cases = []
    for message_id, thread in sorted(threads.items()):
        thread.sort(key=lambda row: (row["CommentCreatedDate"], int(row["CommentId"])))
        feedback_at = next((i for i, row in enumerate(thread) if _is_feedback(row)), None)
        if feedback_at is None:
            continue
        reviewer = (thread[feedback_at].get("CreatorEmail") or "").lower()
        critique = next((row for row in reversed(thread[:feedback_at])
                         if _is_student_critique(row) and (row.get("CreatorEmail") or "").lower() != reviewer), None)
        if critique is None:
            continue
        visible = thread[: thread.index(critique) + 1]  # up to the critique, never the answer
        cases.append(_case(message_id, critique, visible, thread[feedback_at]))
    return cases


# Markers are read from the comment text, not the extract's MarkerType column:
# SQL labels a comment by its FIRST marker, so a reviewer's feedback that
# quotes "##Critique##" is labelled Critique (4 of the first 15 ST0 cases).
def _is_feedback(row: dict) -> bool:
    return "FeedbackGiven" in detect_review_markers(row["Comment"])


def _is_student_critique(row: dict) -> bool:
    markers = set(detect_review_markers(row["Comment"]))
    return classify_critique_marker(row["Comment"]) is not None and not markers & {"FeedbackGiven", "Approved"}


def _case(message_id: str, critique: dict, visible: List[dict], feedback: dict) -> Case:
    authors: Dict[str, int] = {}
    comments = []
    for row in visible:
        attachments, links = extract_attachments_and_links(row["Comment"])
        comments.append(SubmissionComment(
            comment_id=int(row["CommentId"]), created_at=_parse_time(row["CommentCreatedDate"]),
            author_id=authors.setdefault((row.get("CreatorEmail") or "").lower(), len(authors) + 1),
            content_html=row["Comment"], attachments=attachments, links=links,
        ))
    submission = Submission(
        message_id=int(message_id), title=critique["StepName"], created_at=comments[0].created_at,
        content_html="", comments=comments,
    )
    return Case(
        project_id=critique["BCP_ID"], step_name=critique["StepName"], submission=submission,
        comment_id=int(critique["CommentId"]), human_feedback_text=html_to_text(feedback["Comment"]),
    )


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace(" ", "T")[:26])
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class CostEstimate(BaseModel):
    calls: int
    input_tokens: int
    cached_tokens: int  # the system prompt, read from cache after the first call
    expected_usd: float
    worst_case_usd: float


def estimate_cost(stage_input_tokens: List[int], system_size: int, max_tokens: int) -> CostEstimate:
    """Expected: the system prompt is written to the cache once and read by
    every later call; each call returns EXPECTED_OUTPUT_TOKENS.
    Worst case: no cache hits (every call pays a cache write) and every call
    uses the full max_tokens."""
    calls = len(stage_input_tokens)
    total_input = sum(stage_input_tokens)
    uncached = total_input - calls * system_size
    expected = (
        uncached * PRICE_INPUT
        + system_size * PRICE_CACHE_WRITE
        + max(calls - 1, 0) * system_size * PRICE_CACHE_READ
        + calls * EXPECTED_OUTPUT_TOKENS * PRICE_OUTPUT
    ) / 1_000_000
    worst = (uncached * PRICE_INPUT + calls * system_size * PRICE_CACHE_WRITE
             + calls * max_tokens * PRICE_OUTPUT) / 1_000_000
    return CostEstimate(calls=calls, input_tokens=total_input, cached_tokens=system_size,
                        expected_usd=round(expected, 4), worst_case_usd=round(worst, 4))


def actual_cost(results: List[EvaluationResult]) -> float:
    usd = 0.0
    for result in results:
        usage = result.usage
        usd += (usage.input_tokens * PRICE_INPUT + usage.cache_creation_input_tokens * PRICE_CACHE_WRITE
                + usage.cache_read_input_tokens * PRICE_CACHE_READ + usage.output_tokens * PRICE_OUTPUT)
    return round(usd / 1_000_000, 4)


def human_mentions(feedback_text: str) -> List[str]:
    return [rule_id for rule_id, pattern in RULE_HINTS.items() if re.search(pattern, feedback_text, re.IGNORECASE)]


def render_report(cases: List[Case], results: Dict[int, Optional[EvaluationResult]],
                  errors: Dict[int, str]) -> str:
    lines = ["# ST0 historical comparison: AI draft vs human feedback", "",
             "Human mentions are keyword HINTS; read the reviewer's text to judge.", ""]
    agree = ai_only = human_only = 0
    for number, case in enumerate(cases, start=1):
        result = results.get(case.comment_id)
        lines += [f"## {number}. Project {case.project_id}, comment {case.comment_id}", ""]
        if result is None:
            lines += [f"Not evaluated: {errors.get(case.comment_id, 'unknown error')}", ""]
            continue
        flagged = {f.rule_id: f for f in result.findings}
        mentioned = set(human_mentions(case.human_feedback_text))
        lines += [f"Stages evaluated: {result.stages_evaluated}; tokens: {result.usage.total}", "",
                  "| Rule | AI | Human mentions (hint) |", "|---|---|---|"]
        for rule_id in sorted(set(result.passed_rule_ids) | set(flagged) | mentioned):
            ai = flagged[rule_id].status if rule_id in flagged else ("PASS" if rule_id in result.passed_rule_ids else "not evaluated")
            human = "yes" if rule_id in mentioned else ""
            lines.append(f"| {rule_id} | {ai} | {human} |")
            if rule_id in flagged and flagged[rule_id].status == "FAIL":
                agree += rule_id in mentioned
                ai_only += rule_id not in mentioned
            elif rule_id in mentioned and ai == "PASS":
                human_only += 1
        lines += [""] + [f"- **{f.rule_id} {f.status}** ({f.confidence:.2f}): {f.suggested_feedback}" for f in result.findings]
        lines += ["", "Human feedback:", "", "> " + case.human_feedback_text.replace("\n", "\n> "), ""]
    lines += ["## Summary (hints)", "",
              f"- AI FAIL and human mentioned the rule: {agree}",
              f"- AI FAIL, human did not mention it: {ai_only}",
              f"- AI PASS, human mentioned it: {human_only}",
              f"- Cases evaluated: {sum(r is not None for r in results.values())} of {len(cases)}",
              f"- Actual cost: ${actual_cost([r for r in results.values() if r is not None])}"]
    return "\n".join(lines) + "\n"
