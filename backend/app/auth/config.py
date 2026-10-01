"""Sign-in settings (STORY-014, REQ-020), read from environment variables.

AUTH_BOOTSTRAP_ADMIN_EMAILS  Comma-separated Basecamp emails that are always
                             admins. They cannot be removed or demoted from the
                             app, so the role list can never lock every admin
                             out (user decision 2026-10-01). Empty = none.
AUTH_BASECAMP_CLIENT_ID      The Basecamp integration used for sign-in:
AUTH_BASECAMP_CLIENT_SECRET  normally the posting app's own (same id and
AUTH_BASECAMP_REDIRECT_URI   secret; user decision 2026-10-01, revised the same
                             day), though a separate one also works. The
                             redirect URI must match the registration exactly
                             and end in /auth/callback; https, or http only on
                             localhost.
AUTH_COOKIE_SECURE           "no" only for http://localhost. Default yes.
BASECAMP_ACCOUNT_ID          Shared with the posting app: only members of this
BASECAMP_USER_AGENT          Basecamp account may sign in.

Missing sign-in values do not stop the app: sign-in then refuses with "not
configured" (missing_settings names them). Malformed values raise.

Real emails belong in the git-ignored .env only (public repo). Errors name the
variable and the position of a bad entry, never the entry itself.
"""
import os
import re
from typing import FrozenSet, List, Mapping, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, SecretStr

# People are matched on their Basecamp email (user decision 2026-10-01). Kept
# within the audit trail's id length, so an email can be an actor_id.
MAX_EMAIL_LENGTH = 128
_EMAIL = re.compile(r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$")


class AuthConfigError(Exception):
    error_class = "ConfigError"


class InvalidEmail(ValueError):
    error_class = "ValidationError"


def normalize_email(raw: str) -> str:
    """Trimmed and lower-cased, so 'Ann@X.com ' and 'ann@x.com' are one person.
    Raises InvalidEmail (message never repeats the value) when it is not an email."""
    email = raw.strip().lower()
    if not email or len(email) > MAX_EMAIL_LENGTH or not _EMAIL.match(email):
        raise InvalidEmail(f"not a valid email address (at most {MAX_EMAIL_LENGTH} characters)")
    return email


class AuthConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    bootstrap_admin_emails: FrozenSet[str] = frozenset()
    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    redirect_uri: str = ""
    cookie_secure: bool = True
    account_id: Optional[int] = None
    user_agent: str = ""

    @property
    def missing_settings(self) -> List[str]:
        """Names (never values) of the settings sign-in still needs."""
        present = {"AUTH_BASECAMP_CLIENT_ID": self.client_id,
                   "AUTH_BASECAMP_CLIENT_SECRET": self.client_secret.get_secret_value(),
                   "AUTH_BASECAMP_REDIRECT_URI": self.redirect_uri,
                   "BASECAMP_ACCOUNT_ID": self.account_id, "BASECAMP_USER_AGENT": self.user_agent}
        return [name for name, value in present.items() if not value]


def load_auth_config(environ: Optional[Mapping[str, str]] = None) -> AuthConfig:
    env = os.environ if environ is None else environ
    problems: List[str] = []
    admins = set()
    raw = env.get("AUTH_BOOTSTRAP_ADMIN_EMAILS", "")
    for position, part in enumerate(raw.split(","), start=1):
        if not part.strip():
            continue
        try:
            admins.add(normalize_email(part))
        except InvalidEmail:
            problems.append(f"AUTH_BOOTSTRAP_ADMIN_EMAILS entry {position} is not a valid email address")

    redirect_uri = env.get("AUTH_BASECAMP_REDIRECT_URI", "").strip()
    if redirect_uri and not _redirect_ok(redirect_uri):
        problems.append("AUTH_BASECAMP_REDIRECT_URI must be https://.../auth/callback "
                        "(http only on localhost)")
    secure_raw = env.get("AUTH_COOKIE_SECURE", "").strip().lower()
    if secure_raw not in ("", "yes", "no"):
        problems.append("AUTH_COOKIE_SECURE must be yes or no")
    account_raw = env.get("BASECAMP_ACCOUNT_ID", "").strip()
    if account_raw and (not account_raw.isdigit() or int(account_raw) <= 0):
        problems.append("BASECAMP_ACCOUNT_ID must be a positive whole number")
    if problems:
        raise AuthConfigError("; ".join(problems))
    return AuthConfig(bootstrap_admin_emails=frozenset(admins),
                      client_id=env.get("AUTH_BASECAMP_CLIENT_ID", "").strip(),
                      client_secret=SecretStr(env.get("AUTH_BASECAMP_CLIENT_SECRET", "").strip()),
                      redirect_uri=redirect_uri, cookie_secure=secure_raw != "no",
                      account_id=int(account_raw) if account_raw else None,
                      user_agent=env.get("BASECAMP_USER_AGENT", "").strip())


def _redirect_ok(uri: str) -> bool:
    parsed = urlparse(uri)
    local = parsed.hostname in ("localhost", "127.0.0.1")
    return (parsed.scheme == "https" or (parsed.scheme == "http" and local)) \
        and bool(parsed.hostname) and parsed.path.endswith("/auth/callback")
