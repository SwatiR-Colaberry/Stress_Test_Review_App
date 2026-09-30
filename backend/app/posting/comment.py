"""The Basecamp comment that carries a review's final feedback (STORY-006).

Shape (Basecamp rich text is HTML made of <div> lines):

    <div>1. First approved finding…</div>
    <div>2. …</div>
    <div><br></div>
    <div>Review ref: FB-1a2b3c4d5e6f</div>
    <div>##FeedbackGiven##</div>

- The feedback text is HTML-escaped line by line, so reviewer text can never
  inject markup into Basecamp.
- "Review ref" is the feedback id. It is derived from the review id, so the
  same review always gets the same ref. Before posting (and before every
  retry) the thread is searched for it: found means already posted, which is
  how a retry after a timeout never posts twice (user decision 2026-09-30).
- ##FeedbackGiven## is the marker reviewers write today. STORY-001 intake
  treats a comment with it as the reviewer's, so it never opens a new review.
"""
import hashlib
import html

FEEDBACK_GIVEN_MARKER = "##FeedbackGiven##"


def feedback_id_for(review_id: str) -> str:
    """Stable, non-guessable-from-content id for one review's feedback."""
    return "FB-" + hashlib.sha256(review_id.encode("utf-8")).hexdigest()[:12]


def build_comment_html(feedback_text: str, feedback_id: str) -> str:
    lines = [
        f"<div>{html.escape(line)}</div>" if line.strip() else "<div><br></div>"
        for line in feedback_text.strip().splitlines()
    ]
    footer = ["<div><br></div>", f"<div>Review ref: {feedback_id}</div>", f"<div>{FEEDBACK_GIVEN_MARKER}</div>"]
    return "".join(lines + footer)


def contains_feedback_id(content_html: str, feedback_id: str) -> bool:
    """True if a Basecamp comment already carries this feedback's ref.
    Matches the id alone (FB- + 12 hex, unique per review): Basecamp may store
    the text around it differently (e.g. the space as &nbsp;, or added tags),
    and the id is letters, digits and one hyphen, so escaping cannot change it."""
    return bool(content_html) and feedback_id in content_html
