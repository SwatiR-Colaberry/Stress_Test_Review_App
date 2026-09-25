"""One-time Basecamp OAuth 2.0 authorization (REQ-012), used by
backend/scripts/basecamp_oauth_setup.py.

Flow (Basecamp Launchpad, authorization-code grant):
  1. authorize_url(): the user opens it and clicks Allow in their browser.
  2. wait_for_callback(): a one-shot listener on the localhost redirect URI
     receives ?code=...&state=...; the state must match (CSRF protection).
  3. exchange_code(): POST the code for an access token and refresh token.
  4. fetch_basecamp_accounts(): which Basecamp accounts the token can see.
  5. update_env_file(): write BASECAMP_* values to the git-ignored .env.

Failure handling:
- Every HTTP call has an explicit timeout.
- The code exchange is a POST with a single-use code: it is retried only when
  the connection could not be opened (the request never reached Basecamp), at
  most 3 attempts. A timeout after sending is NOT retried, since the code may
  already be spent; the user re-runs the script instead.
- The account lookup is a read, retried on network errors and 5xx (3 attempts).
- Launchpad refusing the code/secret raises OAuthError with the HTTP status and
  Launchpad's short error code only, never the response body or any secret.
- No token, secret or code is ever logged or included in an error message.
"""
import html
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr

LAUNCHPAD = "https://launchpad.37signals.com"
# Launchpad product codes for the current Basecamp API (3.basecampapi.com).
# Basecamp 4 accounts have been reported as "bc3"; "bc4" is accepted in case.
# Basecamp 2 ("bcx") and Classic use a different, older API and are excluded.
_BASECAMP_PRODUCTS = ("bc3", "bc4")


class OAuthError(Exception):
    """Authorization failed. Messages never contain secrets or response bodies."""


class OAuthTokens(BaseModel):
    model_config = ConfigDict(frozen=True)
    access_token: SecretStr
    refresh_token: SecretStr
    expires_in: Optional[int] = None


class BasecampAccount(BaseModel):
    id: int
    name: str


def new_state() -> str:
    return secrets.token_urlsafe(24)


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode({"type": "web_server", "client_id": client_id, "redirect_uri": redirect_uri, "state": state})
    return f"{LAUNCHPAD}/authorization/new?{query}"


def check_redirect_uri(redirect_uri: str) -> None:
    """The setup script listens locally, so the redirect must be plain http on this machine."""
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1") or not parsed.port:
        raise OAuthError("BASECAMP_REDIRECT_URI must look like http://localhost:8765/basecamp/oauth/callback")


def wait_for_callback(redirect_uri: str, expected_state: str, timeout_s: float = 180.0) -> str:
    """Serves the redirect URI until Basecamp calls it once; returns the code."""
    check_redirect_uri(redirect_uri)
    parsed = urlparse(redirect_uri)
    result: Dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib name)
            request = urlparse(self.path)
            if request.path != parsed.path:
                self.send_response(404)
                self.end_headers()
                return
            params = {k: v[0] for k, v in parse_qs(request.query).items()}
            result.update(params)
            ok = "code" in params and params.get("state") == expected_state
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = "Basecamp access granted. You can close this tab." if ok else "Authorization failed. Check the terminal."
            self.wfile.write(f"<p>{html.escape(message)}</p>".encode())

        def log_message(self, *args: object) -> None:  # the URL holds the code: keep it out of stderr
            return

    deadline = time.monotonic() + timeout_s
    with HTTPServer((parsed.hostname, parsed.port), Handler) as server:
        while not result:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OAuthError(f"No response from Basecamp within {int(timeout_s)} s; run the script again")
            server.timeout = min(remaining, 1.0)
            server.handle_request()

    if "error" in result:
        raise OAuthError(f"Basecamp returned error '{result['error'][:40]}' (was access denied?)")
    if result.get("state") != expected_state:
        raise OAuthError("State mismatch: the callback did not come from this authorization; run again")
    if not result.get("code"):
        raise OAuthError("Callback had no authorization code")
    return result["code"]


def exchange_code(
    client_id: str, client_secret: SecretStr, redirect_uri: str, code: str,
    transport: Optional[httpx.BaseTransport] = None, timeout_s: float = 15.0,
    max_attempts: int = 3, backoff_s: Sequence[float] = (1.0, 2.0),
    sleep: Callable[[float], None] = time.sleep,
) -> OAuthTokens:
    form = {"type": "web_server", "client_id": client_id, "redirect_uri": redirect_uri,
            "client_secret": client_secret.get_secret_value(), "code": code}
    with httpx.Client(timeout=timeout_s, transport=transport) as http:
        for attempt in range(1, max_attempts + 1):
            try:
                response = http.post(f"{LAUNCHPAD}/authorization/token", data=form)
                break
            except httpx.ConnectError:  # request never sent: safe to retry
                if attempt == max_attempts:
                    raise OAuthError(f"Could not reach Basecamp Launchpad after {attempt} attempts") from None
                sleep(backoff_s[min(attempt - 1, len(backoff_s) - 1)])
            except httpx.TransportError as exc:  # may have been sent: the code may be spent
                raise OAuthError(f"Token exchange interrupted ({type(exc).__name__}); run the script again") from None
    if response.status_code != 200:
        raise OAuthError(f"Launchpad refused the token exchange (HTTP {response.status_code}, "
                         f"error '{_launchpad_error(response)}'). Check client id/secret and redirect URI.")
    try:
        return OAuthTokens.model_validate(response.json())
    except ValueError:
        raise OAuthError("Launchpad token response was not the expected shape") from None


def fetch_basecamp_accounts(
    access_token: SecretStr, user_agent: str, transport: Optional[httpx.BaseTransport] = None,
    timeout_s: float = 15.0, max_attempts: int = 3, backoff_s: Sequence[float] = (1.0, 2.0),
    sleep: Callable[[float], None] = time.sleep,
) -> List[BasecampAccount]:
    headers = {"Authorization": f"Bearer {access_token.get_secret_value()}", "User-Agent": user_agent}
    with httpx.Client(timeout=timeout_s, transport=transport, headers=headers) as http:
        for attempt in range(1, max_attempts + 1):
            try:
                response = http.get(f"{LAUNCHPAD}/authorization.json")
            except httpx.TransportError:
                response = None
            if response is not None and response.status_code < 500:
                break
            if attempt == max_attempts:
                raise OAuthError(f"Could not read Basecamp accounts after {attempt} attempts")
            sleep(backoff_s[min(attempt - 1, len(backoff_s) - 1)])
    if response.status_code != 200:
        raise OAuthError(f"Launchpad refused the new token (HTTP {response.status_code})")
    try:
        accounts = response.json().get("accounts", [])
        return [BasecampAccount(id=a["id"], name=a.get("name", "")) for a in accounts
                if isinstance(a, dict) and a.get("product") in _BASECAMP_PRODUCTS]
    except (ValueError, AttributeError, KeyError, TypeError):
        raise OAuthError("Launchpad authorization response was not the expected shape") from None


def update_env_file(path: Path, updates: Mapping[str, str]) -> None:
    """Sets the given KEY=value lines in .env (replacing or appending), keeping
    every other line. Written atomically and readable by the owner only."""
    for key, value in updates.items():
        if not key.startswith("BASECAMP_") or any(ch in value for ch in '"\n\r'):
            raise OAuthError(f"Refusing to write {key}: unexpected key or characters in value")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(updates)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f'{key}="{remaining.pop(key)}"')
        else:
            out.append(line)
    out.extend(f'{key}="{value}"' for key, value in remaining.items())
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n")
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def _launchpad_error(response: httpx.Response) -> str:
    try:
        value = response.json().get("error", "unknown")
    except (ValueError, AttributeError):
        return "unknown"
    return str(value)[:40]
