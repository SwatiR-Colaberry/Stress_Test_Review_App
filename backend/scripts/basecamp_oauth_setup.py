"""One-off operational script: authorize this app with Basecamp (OAuth 2.0,
REQ-012) and save the resulting tokens to the local, git-ignored .env.

Needs in .env first (see .env.example): BASECAMP_CLIENT_ID,
BASECAMP_CLIENT_SECRET, BASECAMP_REDIRECT_URI (http://localhost:<port>/...,
exactly as registered at launchpad.37signals.com/integrations) and
BASECAMP_USER_AGENT.

Run from the repo root:  .venv/bin/python backend/scripts/basecamp_oauth_setup.py [--account-id N]
Opens your browser; sign in to Basecamp and click Allow. Writes
BASECAMP_ACCESS_TOKEN, BASECAMP_REFRESH_TOKEN and BASECAMP_ACCOUNT_ID to .env
(mode 600). Never prints a token. Safe to re-run: it replaces those lines.
The access token expires after about two weeks; re-run to get a new one.
Exit codes: 0 ok, 1 configuration problem, 2 authorization failed,
3 account choice needed or no Basecamp account found.
"""
import argparse
import os
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from app.basecamp import oauth  # noqa: E402

ENV_PATH = REPO_ROOT / ".env"
REQUIRED = ("BASECAMP_CLIENT_ID", "BASECAMP_CLIENT_SECRET", "BASECAMP_REDIRECT_URI", "BASECAMP_USER_AGENT")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--account-id", type=int, help="which Basecamp account, if the login can see several")
    args = parser.parse_args(argv)

    load_dotenv(ENV_PATH, override=False)
    missing = [var for var in REQUIRED if not os.environ.get(var, "").strip()]
    if missing:
        print(f"CONFIG ERROR: missing in .env: {', '.join(missing)}")
        return 1
    client_id = os.environ["BASECAMP_CLIENT_ID"].strip()
    client_secret = SecretStr(os.environ["BASECAMP_CLIENT_SECRET"].strip())
    redirect_uri = os.environ["BASECAMP_REDIRECT_URI"].strip()
    user_agent = os.environ["BASECAMP_USER_AGENT"].strip()

    try:
        oauth.check_redirect_uri(redirect_uri)
        state = oauth.new_state()
        url = oauth.authorize_url(client_id, redirect_uri, state)
        print("Opening Basecamp in your browser. Sign in and click 'Yes, I'll allow access'.")
        print(f"If it does not open, paste this into your browser:\n  {url}")
        webbrowser.open(url)
        code = oauth.wait_for_callback(redirect_uri, state)
        tokens = oauth.exchange_code(client_id, client_secret, redirect_uri, code)
        accounts = oauth.fetch_basecamp_accounts(tokens.access_token, user_agent)
    except oauth.OAuthError as exc:
        print(f"AUTHORIZATION FAILED: {exc}")
        return 2
    except OSError as exc:  # e.g. the redirect port is already in use
        print(f"AUTHORIZATION FAILED: cannot listen on {redirect_uri} ({type(exc).__name__})")
        return 2

    account = _choose_account(accounts, args.account_id)
    if account is None:
        return 3
    oauth.update_env_file(ENV_PATH, {
        "BASECAMP_ACCOUNT_ID": str(account.id),
        "BASECAMP_ACCESS_TOKEN": tokens.access_token.get_secret_value(),
        "BASECAMP_REFRESH_TOKEN": tokens.refresh_token.get_secret_value(),
    })
    print(f"Authorized for Basecamp account {account.id} ({account.name}). Tokens saved to .env (not printed).")
    print("Next: .venv/bin/python backend/scripts/retrieve_submissions.py --project-id <id> --user-id <you>")
    return 0


def _choose_account(accounts: List[oauth.BasecampAccount], wanted: Optional[int]) -> Optional[oauth.BasecampAccount]:
    if not accounts:
        print("NO BASECAMP ACCOUNT: this login cannot see any Basecamp 3/4 account.")
        return None
    if wanted is not None:
        match = next((a for a in accounts if a.id == wanted), None)
        if match is None:
            print(f"ACCOUNT NOT FOUND: {wanted} is not one of: {', '.join(str(a.id) for a in accounts)}")
        return match
    if len(accounts) > 1:
        print("SEVERAL ACCOUNTS: re-run with --account-id, one of:")
        for a in accounts:
            print(f"  {a.id}  {a.name}")
        return None
    return accounts[0]


if __name__ == "__main__":
    sys.exit(main())
