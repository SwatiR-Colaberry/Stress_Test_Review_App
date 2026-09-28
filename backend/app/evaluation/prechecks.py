"""Deterministic pre-checks (STORY-004).

Cheap facts computed in Python before any Claude call and passed to Claude,
so it does not spend tokens counting or searching. They are inputs to
Claude's judgement, not findings: a split submission, an unusual problem
layout or a link in an earlier comment can make any of them misleading, and
the prompt says so.
"""
import re
from statistics import median_low
from typing import List, Optional
from urllib.parse import urlparse

from app.evaluation.input_check import EvaluationInput
from app.models import PrecheckResults

# "Problem 3", "Problem #3", "Problem No. 3", "Problem 3:", "Problem-3"
_PROBLEM_NUMBER = re.compile(r"\bproblem\s*(?:#|no\.?|number)?\s*[-:]?\s*(\d{1,2})\b", re.IGNORECASE)
_SELECTED = re.compile(r"\[SELECTED\]")
# Students often paste a URL as text instead of a Basecamp link: count both.
_BARE_URL = re.compile(r"https?://[^\s\])>\"']+")

# What may precede a field label at the start of a line: a bullet, a
# [SELECTED] marker, "1." / "1.2." / "1)" numbering, or a keycap emoji "1️⃣".
_LEAD = r"^(?:[-*•]\s*)?(?:\[SELECTED\]\s*)?(?:\d+\s*[.)]\s*(?:\d+\s*[.)]?\s*)?|\d\ufe0f?\u20e3\s*)?"

# (host, required path prefix)
DATASET_HOSTS = (
    ("kaggle.com", ""),
    ("data.gov", ""),
    ("archive.ics.uci.edu", ""),
    ("data.world", ""),
    ("huggingface.co", "/datasets"),
    ("zenodo.org", ""),
)
DATASET_EXTENSIONS = (".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet", ".zip")
DATASET_CONTENT_TYPES = (
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/zip",
    "application/x-zip-compressed",
)


def count_numbered_problems(text: str) -> int:
    """Distinct problem numbers mentioned, e.g. "Problem 1" ... "Problem 9".
    "Selected Problem: Problem #3" repeats a number and adds nothing."""
    return len({int(number) for number in _PROBLEM_NUMBER.findall(text) if int(number) > 0})


def _label_pattern(field: str) -> "re.Pattern[str]":
    """A field label at the start of a line: "Solution:", "- Solutions -",
    "3. Target Audience:", "Problem 2:", "Problem Statement:".
    "Model Type/s" -> Model Types?; "Future Capability/ies" -> Capabilit(y|ies)."""
    stem = field.split("/")[0].strip()
    word = re.escape(stem[:-1]) + "(?:y|ies)" if stem.endswith("y") else re.escape(stem) + "s?"
    word = word.replace(r"\ ", r"\s+")
    return re.compile(
        _LEAD + word + r"\b(?:\s*(?:#\s*)?\d+)?\s*(?:statement)?\s*(?:[:\-–]|$)", re.IGNORECASE | re.MULTILINE
    )


def estimate_problem_count(text: str, required_fields: List[str]) -> Optional[int]:
    """How many problems the submission holds, or None when it cannot be told.

    Most ST0 submissions do not number their problems; each is a block of
    labelled fields. So each required field's label is counted, together with
    distinct problem numbers, and the median of the non-zero counts is used
    (one mislabelled field does not move it). On the 45 ST0 ##Critique##
    comments of the 2026-09-25 per-Stress-Test extract, numbering alone gives a
    count for 12; with the field labels, 36 get one (20 of them 10). The other
    9 use a layout without labels at line starts, or hold no problems, and get
    None, never a misleading 0.
    """
    counts = [len(_label_pattern(field).findall(text)) for field in required_fields]
    counts.append(count_numbered_problems(text))
    found = [count for count in counts if count > 0]
    return median_low(found) if found else None


def _is_dataset_link(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return any(
        (host == known or host.endswith("." + known)) and parsed.path.startswith(path)
        for known, path in DATASET_HOSTS
    )


def run_prechecks(checked: EvaluationInput) -> PrecheckResults:
    files = checked.attachments
    dataset_files = [
        a for a in files
        if (a.content_type or "").lower() in DATASET_CONTENT_TYPES
        or (a.filename or "").lower().endswith(DATASET_EXTENSIONS)
    ]
    images = [a for a in files if (a.content_type or "").lower().startswith("image/")]
    urls = {link.url.rstrip("/.,;") for link in checked.links}
    urls |= {url.rstrip("/.,;") for url in _BARE_URL.findall(checked.content_text)}
    return PrecheckResults(
        problem_count=estimate_problem_count(checked.content_text, checked.module.required_problem_fields),
        selected_count=len(_SELECTED.findall(checked.content_text)),
        link_count=len(urls),
        dataset_link_present=any(_is_dataset_link(url) for url in urls),
        dataset_file_count=len(dataset_files),
        image_count=len(images),
    )
