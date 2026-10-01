"""Signed-in sessions (STORY-014, REQ-020).

A session is a random token the browser keeps in an HttpOnly cookie. The
server keeps only the token's SHA-256 hash, so a leaked session list (or a
log line) cannot be replayed as a cookie. The raw token is never stored or
logged.

Lifetime: a fixed 8 hours from sign-in (acceptance: "when they sign out or 8
hours pass, then they must sign in again"). No sliding renewal: activity does
not extend it. Sign-out ends it at once.

The role is looked up again on every request, so removing or demoting someone
takes effect on their next click, not when their session ends.

Storage: in memory. A server restart signs everyone out, which is the safe
direction to fail. Not handled: sharing sessions between several server
processes (would need a shared store).
"""
import hashlib
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from app.auth.roles import Role, RoleStore

SESSION_LIFETIME = timedelta(hours=8)
SESSION_COOKIE = "str_session"
# secrets.token_urlsafe(32) is 43 characters; anything far longer is not ours.
MAX_TOKEN_LENGTH = 128
MAX_NAME_LENGTH = 200

Clock = Callable[[], datetime]


class Session(BaseModel):
    """What the server remembers about one sign-in. Never holds the token."""
    model_config = ConfigDict(frozen=True)

    email: str
    name: str = Field(max_length=MAX_NAME_LENGTH)
    signed_in_at: datetime
    expires_at: datetime


class Principal(BaseModel):
    """The signed-in person for one request, with their role as of now."""
    model_config = ConfigDict(frozen=True)

    email: str
    name: str
    role: Role
    expires_at: datetime

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class SessionStore:
    def __init__(self, roles: RoleStore, clock: Clock = lambda: datetime.now(timezone.utc),
                 lifetime: timedelta = SESSION_LIFETIME) -> None:
        self._roles = roles
        self._clock = clock
        self._lifetime = lifetime
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()

    def start(self, email: str, name: str) -> Tuple[str, Session]:
        """Opens a session and returns (token for the cookie, session). The
        caller has already checked the person has a role."""
        now = self._clock()
        session = Session(email=email, name=name[:MAX_NAME_LENGTH], signed_in_at=now,
                          expires_at=now + self._lifetime)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._drop_expired(now)
            self._sessions[_hash(token)] = session
        return token, session

    def resolve(self, token: Optional[str]) -> Optional[Principal]:
        """The signed-in person, or None when there is no live session or they
        no longer have a role (their session is then ended). Raises
        RoleStoreUnavailable when the role list cannot be read."""
        key = _key(token)
        if key is None:
            return None
        now = self._clock()
        with self._lock:
            session = self._sessions.get(key)
            if session is not None and now >= session.expires_at:
                del self._sessions[key]
                session = None
        if session is None:
            return None
        role = self._roles.role_for(session.email)
        if role is None:
            self._discard(key)
            return None
        return Principal(email=session.email, name=session.name, role=role, expires_at=session.expires_at)

    def end(self, token: Optional[str]) -> Optional[Session]:
        """Signs out. Returns the ended session (for the audit record), or None
        when there was none; ending twice is harmless."""
        key = _key(token)
        return None if key is None else self._discard(key)

    def _discard(self, key: str) -> Optional[Session]:
        with self._lock:
            return self._sessions.pop(key, None)

    def _drop_expired(self, now: datetime) -> None:
        for key in [k for k, s in self._sessions.items() if now >= s.expires_at]:
            del self._sessions[key]


def _key(token: Optional[str]) -> Optional[str]:
    if not token or len(token) > MAX_TOKEN_LENGTH:
        return None
    return _hash(token)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
