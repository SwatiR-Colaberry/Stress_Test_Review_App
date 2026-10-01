"""Demo: STORY-014 sign in with Basecamp, offline. No real Basecamp, no Claude,
no SQL Server. Everything (role list, reviews, audit trail) is written to a
new temporary folder, never data/.

"Sign in with Basecamp" goes to a DEMO-ONLY page served by this script (the
app never has it) where you choose who to be:
  Demo Reviewer   on the reviewer list           -> Review Queue as a Reviewer
  Demo Admin      a fixed (bootstrap) admin      -> also the Admins page
  Olga Outsider   in our Basecamp, on no list    -> "Access refused"
  Pat Partner     in another Basecamp account    -> "Access refused"
  Cancel          as if you clicked Deny         -> "Access refused"
From there the REAL code runs: code exchange (against a fake Launchpad),
identity, account and role checks, session cookie, page and API guards,
8-hour expiry, sign-out, and the audit trail. Run from the repo root:
  .venv/bin/python backend/scripts/signin_demo.py [--port 8014]
then open the printed URL. The audit file printed at the start shows every
sign-in, refusal, sign-out and role change. Stop with Ctrl+C.
"""
import argparse
import html
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlencode

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

REVIEWER = "demo-reviewer@example.com"
ADMIN = "demo-admin@example.com"
# code -> (button label, email, first name, Basecamp account ids)
PEOPLE = {
    "demo-reviewer": ("Demo Reviewer (on the reviewer list)", REVIEWER, "Demo Reviewer", "ours"),
    "demo-admin": ("Demo Admin (fixed admin)", ADMIN, "Demo Admin", "ours"),
    "olga": ("Olga Outsider (in our Basecamp, on no list)", "olga.outsider@example.com", "Olga", "ours"),
    "pat": ("Pat Partner (another Basecamp account)", "pat.partner@example.com", "Pat", "other"),
}


class DemoEnv(NamedTuple):
    audit_path: Path
    roles_path: Path


def install(app, tmp: Path, base_url: str) -> DemoEnv:
    """Point sign-in at the fake Launchpad and the demo-only chooser page.
    The app's audit trail must already point into `tmp` (AUDIT_TRAIL_PATH)."""
    from fastapi import Query
    from fastapi.responses import HTMLResponse

    from app.audit.dependencies import get_audit_trail
    from app.auth import fake
    from app.auth.dependencies import get_auth_config, get_launchpad_client, get_role_store, get_session_store
    from app.auth.launchpad import LaunchpadClient
    from app.auth.roles import RoleStore
    from app.auth.sessions import SessionStore

    config = fake.fake_config(bootstrap_admin_emails=frozenset({ADMIN}),
                              redirect_uri=f"{base_url}/auth/callback", cookie_secure=False)
    roles = RoleStore(tmp / "auth" / "roles.json", config.bootstrap_admin_emails, get_audit_trail())
    roles.set_role(REVIEWER, "reviewer", ADMIN, "demo-setup")
    sessions = SessionStore(roles)
    launchpad = fake.FakeLaunchpad()
    for code, (_label, email, first_name, accounts) in PEOPLE.items():
        launchpad.add(code, email, first_name, accounts=(fake.ACCOUNT_ID,) if accounts == "ours" else (123,))

    class DemoLaunchpad(LaunchpadClient):
        def authorize_url(self, state: str) -> str:  # the demo chooser instead of Basecamp
            return "/demo-launchpad?" + urlencode({"state": state})

    app.dependency_overrides.update({
        get_auth_config: lambda: config, get_role_store: lambda: roles, get_session_store: lambda: sessions,
        get_launchpad_client: lambda: DemoLaunchpad(config, transport=launchpad.transport(), sleep=lambda _s: None),
    })

    @app.get("/demo-launchpad", response_class=HTMLResponse, include_in_schema=False)
    def demo_launchpad(state: str = Query(max_length=128)) -> HTMLResponse:
        def link(params: dict, label: str) -> str:
            href = html.escape("/auth/callback?" + urlencode({**params, "state": state}))
            return f'<li><a href="{href}">{html.escape(label)}</a></li>'
        items = "".join(link({"code": code}, label) for code, (label, *_rest) in PEOPLE.items())
        items += link({"error": "access_denied"}, "Cancel (as if you clicked Deny in Basecamp)")
        return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Demo Basecamp sign-in</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:520px;margin:10vh auto;padding:0 16px}}
li{{margin:8px 0}} .note{{color:#666}}</style></head><body>
<h1>Demo Basecamp sign-in</h1>
<p class="note">Offline demo only (backend/scripts/signin_demo.py). In real use this is Basecamp's own page.
Choose who to sign in as:</p><ul>{items}</ul></body></html>""")

    return DemoEnv(audit_path=Path(os.environ["AUDIT_TRAIL_PATH"]), roles_path=tmp / "auth" / "roles.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8014)
    args = parser.parse_args()

    # Point every store at a new temporary folder BEFORE the app modules read these.
    tmp = Path(tempfile.mkdtemp(prefix="signin-demo-"))
    os.environ["EVALUATIONS_DIR"] = str(tmp / "evaluations")
    os.environ["REVIEWS_DIR"] = str(tmp / "reviews")
    os.environ["AUDIT_TRAIL_PATH"] = str(tmp / "audit" / "audit_trail.jsonl")
    os.environ["AUTH_ROLES_PATH"] = str(tmp / "auth" / "roles.json")

    import uvicorn
    from fastapi.testclient import TestClient

    import queue_ui_demo
    from app.auth.fake import TestSignIn
    from app.evaluation.store import ResultStore
    from app.main import app
    from app.posting.dependencies import get_posting_store
    from app.review_queue.dependencies import get_review_queue_store

    # A few made-up reviews so the queue is not empty (seeded as the demo reviewer).
    seeder = TestClient(app)
    TestSignIn(app).sign_in(seeder, queue_ui_demo.DEMO_REVIEWER)
    queue_ui_demo.seed(seeder, get_review_queue_store(), ResultStore(tmp / "evaluations"), get_posting_store(),
                       datetime.now(timezone.utc))
    base_url = f"http://127.0.0.1:{args.port}"
    env = install(app, tmp, base_url)
    print(f"Demo data folder: {tmp}")
    print(f"Audit trail: {env.audit_path}")
    print(f"Open: {base_url}/queue/  (you will be asked to sign in)")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
