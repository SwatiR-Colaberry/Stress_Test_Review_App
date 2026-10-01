"""The two small pages sign-in needs: "Sign in with Basecamp" and "Access
refused". Server-rendered, no script; every value inserted is HTML-escaped.
"""
import html
from typing import Optional
from urllib.parse import urlencode

DEFAULT_NEXT = "/queue/"
MAX_NEXT_LENGTH = 512

_STYLE = """
:root { --bg: #f6f7f9; --card: #fff; --ink: #1d2433; --muted: #5b6475; --accent: #1f6feb; --line: #dfe3ea; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #14171c; --card: #1d2128; --ink: #e8ebf0; --muted: #a3abb9; --accent: #5b9dff; --line: #313744; }
}
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, sans-serif; }
main { max-width: 440px; margin: 12vh auto 0; padding: 32px; background: var(--card);
       border: 1px solid var(--line); border-radius: 12px; }
h1 { font-size: 1.3rem; margin: 0 0 12px; }
p { color: var(--muted); margin: 0 0 20px; }
a.button { display: inline-block; padding: 10px 18px; border-radius: 8px; background: var(--accent);
           color: #fff; text-decoration: none; font-weight: 600; }
.note { padding: 10px 12px; border-radius: 8px; border: 1px solid var(--line); color: var(--ink); }
@media (max-width: 480px) { main { margin: 16px; padding: 20px; } }
"""


def safe_next(raw: Optional[str]) -> str:
    """Only a path on this site: blocks //evil.example and /\\evil.example
    (open redirects) and anything odd. Falls back to the Review Queue."""
    if not raw or len(raw) > MAX_NEXT_LENGTH or not raw.startswith("/") or raw.startswith(("//", "/\\")):
        return DEFAULT_NEXT
    if any(ch.isspace() or ord(ch) < 32 or ch == "\\" for ch in raw):
        return DEFAULT_NEXT
    return raw


def sign_in_page(next_path: str, notice: Optional[str] = None) -> str:
    login = "/auth/login?" + urlencode({"next": safe_next(next_path)})
    note = f'<p class="note">{html.escape(notice)}</p>' if notice else ""
    return _page("Sign in", f"""
<h1>Stress Test Review</h1>
{note}
<p>Reviewers and admins sign in with their Basecamp account.</p>
<a class="button" href="{html.escape(login)}">Sign in with Basecamp</a>""")


def refused_page(message: str) -> str:
    return _page("Access refused", f"""
<h1>Access refused</h1>
<p>{html.escape(message)}</p>
<a class="button" href="/auth/signin">Back to sign in</a>""")


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Stress Test Review</title><style>{_STYLE}</style></head>
<body><main>{body}
</main></body></html>"""
