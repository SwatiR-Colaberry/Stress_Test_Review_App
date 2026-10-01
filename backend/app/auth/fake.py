"""Stand-ins for tests and offline demos (STORY-014). Nothing here reaches the
real Basecamp.

FakeLaunchpad   answers the code exchange and identity lookup over an httpx
                MockTransport. Its tokens are fixed fake strings, so tests can
                assert they never appear in logs, audit events or pages.
TestSignIn      opens a real session for a made-up person and puts its cookie
                on a TestClient, so tests of other routes go through the real
                guards (API 401/403 and the page redirect), not a bypass.
"""
from typing import Dict, List, Optional

import httpx

from app.auth.config import AuthConfig
from app.auth.dependencies import get_session_store
from app.auth.launchpad import LaunchpadClient
from app.auth.roles import Role
from app.auth.sessions import SESSION_COOKIE, SessionStore

ACCOUNT_ID = 999001
FAKE_ACCESS_TOKEN = "fake-launchpad-access-token-123"
FAKE_REFRESH_TOKEN = "fake-launchpad-refresh-token-456"
FAKE_CLIENT_SECRET = "fake-sign-in-client-secret-789"


def fake_config(**overrides) -> AuthConfig:
    values = dict(bootstrap_admin_emails=frozenset({"boss@example.com"}), client_id="fake-client",
                  client_secret=FAKE_CLIENT_SECRET, redirect_uri="http://localhost:8000/auth/callback",
                  cookie_secure=False, account_id=ACCOUNT_ID, user_agent="Stress Test Review App (test@example.com)")
    values.update(overrides)
    return AuthConfig(**values)


class FakeLaunchpad:
    """people: OAuth code -> (email, first name, account ids)."""

    def __init__(self) -> None:
        self.people: Dict[str, tuple] = {}
        self.token_status = 200
        self.identity_status = 200
        self.identity_body: Optional[dict] = None  # overrides the normal reply
        self.requests: List[httpx.Request] = []
        self._token_for: Dict[str, str] = {}

    def add(self, code: str, email: str, first_name: str = "Test", accounts=(ACCOUNT_ID,)) -> None:
        self.people[code] = (email, first_name, tuple(accounts))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self, config: AuthConfig) -> LaunchpadClient:
        return LaunchpadClient(config, transport=self.transport(), sleep=lambda _s: None)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/authorization/token":
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            code = dict(httpx.QueryParams(request.content.decode()))["code"]
            if code not in self.people:
                return httpx.Response(400, json={"error": "invalid_grant"})
            token = f"{FAKE_ACCESS_TOKEN}-{code}"
            self._token_for[token] = code
            return httpx.Response(200, json={"access_token": token, "refresh_token": FAKE_REFRESH_TOKEN,
                                             "expires_in": 1209600})
        if request.url.path == "/authorization.json":
            if self.identity_status != 200:
                return httpx.Response(self.identity_status)
            if self.identity_body is not None:
                return httpx.Response(200, json=self.identity_body)
            code = self._token_for.get(request.headers["Authorization"].removeprefix("Bearer "))
            if code is None:
                return httpx.Response(401)
            email, first_name, accounts = self.people[code]
            return httpx.Response(200, json={
                "identity": {"id": 1, "first_name": first_name, "last_name": "Person", "email_address": email},
                "accounts": [{"id": a, "product": "bc3", "name": "Account"} for a in accounts]})
        return httpx.Response(404)


class FixedRoles:
    """A role list held in memory: email -> role. Duck-types RoleStore.role_for."""

    def __init__(self) -> None:
        self.people: Dict[str, Role] = {}

    def role_for(self, email: str) -> Optional[Role]:
        return self.people.get(email.strip().lower())


class TestSignIn:
    """Signs a TestClient in as someone. Installs its own session store as the
    app's (via dependency_overrides), so clearing the overrides signs out."""
    __test__ = False  # not a pytest test class

    def __init__(self, app) -> None:
        self.roles = FixedRoles()
        self.sessions = SessionStore(self.roles)
        app.dependency_overrides[get_session_store] = lambda: self.sessions

    def sign_in(self, client, email: str = "reviewer@example.com", role: Role = "reviewer") -> str:
        self.roles.people[email.lower()] = role
        token, _ = self.sessions.start(email.lower(), email.split("@")[0])
        client.cookies.set(SESSION_COOKIE, token)
        return token


def signed_in_client(app, email: str = "reviewer@example.com", role: Role = "reviewer"):
    """A TestClient signed in as email/role (the common case in route tests)."""
    from fastapi.testclient import TestClient
    client = TestClient(app)
    TestSignIn(app).sign_in(client, email, role)
    return client
