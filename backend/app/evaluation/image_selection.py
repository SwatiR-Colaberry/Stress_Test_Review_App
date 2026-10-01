"""Which images Claude may look at (user decision 2026-10-02). Pure: no I/O.

A submission is read as parts, each starting at a label line such as
"Dataset Screenshot:" or "Problem 3:". An image belongs to the part it sits
under, and a part belongs to the rule whose part_keywords its label names.
Claude sees an image only when:
  - its part belongs to a rule that needs_image (in ST0: the screenshot part,
    ST0-004); images under any other part, or before the first label, are
    never read;
  - it is the LAST image in its part (one image per part);
  - at most MAX_IMAGES in total: the parts of the first image rule come
    first (in ST0 the screenshot part), then later image rules, each in the
    order they appear.
Only the request comment's own images are considered.

Labels: after an optional bullet or number, either "words: ..." with a short
label (at most 6 words) before the colon, or a short line (at most 6 words)
that names a rule's keyword. Matching is on whole words, case-insensitive.
When a label names several rules, a rule that needs an image wins ("Dataset
file & screenshot" is the screenshot part: 8 of the past ST0 images sat under
such labels); otherwise the keyword that appears first wins ("Selected
problem" -> the selection rule, not the problem rule).
"""
import re
from typing import List, Optional, Tuple

from pydantic import BaseModel

from app.models import SubmissionAttachment
from app.rules.module import RuleModule

MAX_IMAGES = 5
MAX_LABEL_WORDS = 6
MAX_LABEL_CHARS = 60

_IMAGE_MARKER = re.compile(r"\[image: [^\]]*\]")
_ANY_MARKER = re.compile(r"\[/?SELECTED\]|\[(?:file|image): [^\]]*\]")
_LEAD = re.compile(r"^\s*(?:[-*•#>]+|\(?\d{1,2}[.)]|[a-z][.)])?\s*", re.IGNORECASE)


class ImagePick(BaseModel):
    attachment: SubmissionAttachment
    rule_id: str  # the image rule whose part it sits under
    part_label: str  # the label of that part, as the student wrote it (cut to 60 characters)


Keywords = List[Tuple["re.Pattern[str]", str]]  # (whole-word pattern, rule id)


def select_images(content_text: str, attachments: List[SubmissionAttachment], module: RuleModule) -> List[ImagePick]:
    """content_text: the request comment as html_to_text() gives it (with [image: ...]
    markers); attachments: that comment's attachments, in document order."""
    image_rules = [rule for rule in module.rules if rule.needs_image]
    if not image_rules:
        return []
    keywords = _keywords(module)
    preferred = frozenset(rule.id for rule in image_rules)
    images = iter([a for a in attachments if (a.content_type or "").lower().startswith("image/")])
    last_in_part: dict = {}  # part number -> (attachment, rule_id, label); a later image replaces an earlier one
    part: Optional[Tuple[int, Optional[str], str]] = None  # (number, rule_id, label)
    for line in content_text.split("\n"):
        label = _label(line, keywords)
        if label is not None:
            part = (part[0] + 1 if part else 1, _rule_for(label, keywords, preferred), label)
        for _ in _IMAGE_MARKER.finditer(line):
            image = next(images, None)
            if image is None:
                break  # more markers than image attachments: nothing to pair them with
            if part is not None:
                last_in_part[part[0]] = (image, part[1], part[2])

    picks: List[ImagePick] = []
    for rule in image_rules:  # the first image rule's parts first, each in document order
        for number in sorted(last_in_part):
            image, rule_id, label = last_in_part[number]
            if rule_id == rule.id and len(picks) < MAX_IMAGES:
                picks.append(ImagePick(attachment=image, rule_id=rule_id, part_label=label[:MAX_LABEL_CHARS]))
    return picks


def _keywords(module: RuleModule) -> Keywords:
    pairs = sorted(((word, rule.id) for rule in module.rules for word in rule.part_keywords), key=lambda p: -len(p[0]))
    return [(re.compile(rf"\b{re.escape(word)}s?\b", re.IGNORECASE), rule_id) for word, rule_id in pairs]


def _label(line: str, keywords: Keywords) -> Optional[str]:
    """The label this line starts, or None if it is not a label line."""
    text = _LEAD.sub("", _ANY_MARKER.sub(" ", line)).strip()
    if not text:
        return None
    head, colon, _ = text.partition(":")
    head = head.strip()
    if colon and head and not head.lower().endswith(("http", "https")) and len(head.split()) <= MAX_LABEL_WORDS \
            and len(head) <= MAX_LABEL_CHARS:
        return head
    if len(text.split()) <= MAX_LABEL_WORDS and len(text) <= MAX_LABEL_CHARS and not text.endswith("."):
        return text if _rule_for(text, keywords) is not None else None
    return None


def _rule_for(label: str, keywords: Keywords, preferred: frozenset = frozenset()) -> Optional[str]:
    """A preferred (image) rule the label names, else the rule whose keyword
    appears first in the label (longest keyword on a tie)."""
    best: Optional[Tuple[int, int, str]] = None  # (not preferred, position, rule id)
    for pattern, rule_id in keywords:
        found = pattern.search(label)
        if found:
            rank = (0 if rule_id in preferred else 1, found.start(), rule_id)
            if best is None or rank[:2] < best[:2]:
                best = rank
    return best[2] if best else None
