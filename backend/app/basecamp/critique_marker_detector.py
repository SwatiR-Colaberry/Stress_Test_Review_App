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
from typing import Optional

_CRITIQUE_MARKER_PATTERN = re.compile(r"##\s?critique\s?##", re.IGNORECASE)


def normalize_critique_marker(comment_body) -> Optional[str]:
    """Returns the canonical '##Critique##' if a valid marker is present, else None."""
    if not isinstance(comment_body, str):
        return None
    return "##Critique##" if _CRITIQUE_MARKER_PATTERN.search(comment_body) else None


def is_critique_marker(comment_body) -> bool:
    return normalize_critique_marker(comment_body) is not None
