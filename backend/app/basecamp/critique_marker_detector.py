"""Normalizes a Basecamp comment body and extracts the canonical critique
marker if a valid one is present. Per Master Spec Sec.4 / REQ-001: must
accept `##Critique##`, `## Critique##`, `##Critique ##`, `## Critique ##`
(any case), and must NOT trigger on `Critique`, `#Critique`, `##Review##`,
or prose that merely contains the word "critique".

Ported from the original Node.js implementation
(backend/src/services/basecamp/critiqueMarkerDetector.js); the regex and
behavior are preserved exactly.
"""
import re
from typing import List, Optional

_CRITIQUE_MARKER_PATTERN = re.compile(r"##\s?critique\s?##", re.IGNORECASE)


def normalize_critique_marker(comment_body) -> Optional[str]:
    """Returns the canonical '##Critique##' if a valid marker is present, else None."""
    if not isinstance(comment_body, str):
        return None
    return "##Critique##" if _CRITIQUE_MARKER_PATTERN.search(comment_body) else None


def is_critique_marker(comment_body) -> bool:
    return normalize_critique_marker(comment_body) is not None


# The two follow-up markers of the review cycle (Master Spec §4-5), matched the
# same way as the critique marker: a single optional space inside each "##",
# any case. Returned in canonical form, in the order they appear in _MARKERS.
_MARKERS = (
    ("Critique", _CRITIQUE_MARKER_PATTERN),
    ("FeedbackGiven", re.compile(r"##\s?feedbackgiven\s?##", re.IGNORECASE)),
    ("Approved", re.compile(r"##\s?approved\s?##", re.IGNORECASE)),
)


def detect_review_markers(comment_body) -> List[str]:
    """All review markers present in a comment, e.g. ["Critique"] or
    ["FeedbackGiven", "Approved"]. Empty for none or non-string input."""
    if not isinstance(comment_body, str):
        return []
    return [name for name, pattern in _MARKERS if pattern.search(comment_body)]
