"""The two small pages sign-in needs: "Sign in with Basecamp" and "Access
refused". Server-rendered, no script; every value inserted is HTML-escaped.
"""
import html
from typing import Optional
from urllib.parse import urlencode

DEFAULT_NEXT = "/queue/"
MAX_NEXT_LENGTH = 512

_STYLE = """
:root { --bg: #f4f5f7; --card: #fff; --ink: #1c2230; --muted: #5f6878; --accent: #2f5f8a; --accent-ink: #fff;
        --line: #e2e5ea; --glow-a: rgba(47, 95, 138, .16); --glow-b: rgba(91, 77, 179, .10);
        --dots: rgba(28, 34, 48, .07); --shadow: 0 1px 2px rgba(20, 30, 50, .06), 0 12px 32px rgba(20, 30, 50, .08); }
@media (prefers-color-scheme: dark) {
  :root { --bg: #14161a; --card: #1c1f24; --ink: #e6e8eb; --muted: #a2a9b3; --accent: #7fb0dc; --accent-ink: #10202e;
          --line: #2f343b; --glow-a: rgba(127, 176, 220, .12); --glow-b: rgba(174, 163, 240, .08);
          --dots: rgba(230, 232, 235, .05); --shadow: 0 12px 32px rgba(0, 0, 0, .35); }
}
* { box-sizing: border-box; }
html { min-height: 100%; }
/* Background is CSS only (no image files): two soft colour glows and a faint dot grid. */
body { margin: 0; min-height: 100vh; color: var(--ink); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
       background:
         radial-gradient(circle at 15% 10%, var(--glow-a), transparent 45%),
         radial-gradient(circle at 88% 85%, var(--glow-b), transparent 40%),
         radial-gradient(var(--dots) 1px, transparent 1.5px) 0 0 / 22px 22px,
         var(--bg); }
main { position: relative; max-width: 440px; margin: 14vh auto 0; padding: 32px; background: var(--card);
       border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow); overflow: hidden; }
main::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 4px;
               background: linear-gradient(90deg, var(--accent), #5b4db3); }
.brand { display: flex; gap: 10px; align-items: center; margin: 0 0 18px; color: var(--muted); font-size: 14px; }
.brand-mark { width: 32px; height: 32px; border-radius: 8px; background: var(--accent); color: var(--accent-ink);
              display: grid; place-items: center; font-weight: 700; font-size: 14px; }
h1 { font-size: 1.35rem; margin: 0 0 12px; }
p { color: var(--muted); margin: 0 0 20px; }
a.button { display: inline-block; padding: 10px 18px; border-radius: 8px; background: var(--accent);
           color: var(--accent-ink); text-decoration: none; font-weight: 600; }
a.button:hover { filter: brightness(1.08); }
a.button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.note { padding: 10px 12px; border-radius: 8px; border: 1px solid var(--line); color: var(--ink); }
@media (max-width: 480px) { main { margin: 16px; padding: 24px 20px; } }
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
<body><main><div class="brand" aria-hidden="true"><span class="brand-mark">ST</span>Stress Test Review</div>{body}
</main></body></html>"""
