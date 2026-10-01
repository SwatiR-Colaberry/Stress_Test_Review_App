"""Route protection (STORY-014): no session -> nothing shown or changed;
Reviewers refused admin-only actions; sessions end after 8 hours; admins
manage roles over HTTP with every change audited.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.audit.dependencies import get_audit_trail
from app.audit.trail import InMemoryAuditTrail
from app.auth.dependencies import get_role_store, get_session_store
from app.auth.page_guard import is_protected_page
from app.auth.roles import RoleStore
from app.auth.sessions import SESSION_COOKIE, SessionStore
from app.main import app

BOOT = "boss@example.com"
OPEN_PATHS = {"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


class Clock:
    now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path):
    audit = InMemoryAuditTrail()
    roles = RoleStore(tmp_path / "roles.json", frozenset({BOOT}), audit)
    roles.set_role("rita@example.com", "reviewer", BOOT, "setup")
    roles.set_role("adam@example.com", "admin", BOOT, "setup")
    clock = Clock()
    sessions = SessionStore(roles, clock=clock)
    app.dependency_overrides.update({get_audit_trail: lambda: audit, get_role_store: lambda: roles,
                                     get_session_store: lambda: sessions})

    def client_for(email=None):
        client = TestClient(app)
        if email:
            client.cookies.set(SESSION_COOKIE, sessions.start(email, email.split("@")[0])[0])
        return client

    yield type("Env", (), dict(audit=audit, roles=roles, sessions=sessions, clock=clock, client_for=client_for,
                               path=tmp_path / "roles.json"))
    app.dependency_overrides.clear()


def _api_routes():
    """Every API the app serves, from its own OpenAPI schema (this FastAPI
    version wraps included routers, so app.routes does not list them)."""
    for path, operations in app.openapi()["paths"].items():
        if path not in OPEN_PATHS and not path.startswith("/auth/"):
            for method in operations:
                yield method.upper(), path.replace("{review_id}", "r-1").replace("{email}", "x@example.com")


API_ROUTES = sorted(set(_api_routes()))
PAGES = ["/queue/", "/queue/queue.js", "/reviewer/", "/reviewer/?review=r-1", "/reviewer/reviewer.js",
         "/rules/", "/rules/rules.css", "/admin/"]


# --- no session: nothing shown or changed ------------------------------------------

def test_the_route_sweep_covers_every_review_api():
    paths = {p for _m, p in API_ROUTES}
    assert {"/reviews/queue", "/reviews/r-1/findings", "/reviews/r-1/actions", "/reviews/r-1/prepare",
            "/reviews/r-1/post", "/queue-ui/reviews", "/queue-ui/reviews/r-1", "/rules-ui/modules",
            "/basecamp/comments/process", "/reviews/finalize-check", "/admin-ui/roles"} <= paths


@pytest.mark.parametrize("method, path", API_ROUTES)
def test_without_a_session_every_api_is_401_and_changes_nothing(env, method, path):
    response = env.client_for().request(method, path, json={}, follow_redirects=False)
    assert response.status_code == 401, (method, path)
    assert response.json()["detail"]["reason_code"] == "NOT_SIGNED_IN"
    assert env.audit.read_all()[2:] == []  # only the two setup events


@pytest.mark.parametrize("path", PAGES)
def test_without_a_session_every_page_sends_you_to_sign_in(env, path):
    response = env.client_for().get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/auth/signin?next=%2F")
    assert "<html" not in response.text


def test_the_redirect_remembers_the_page_and_its_query(env):
    response = env.client_for().get("/reviewer/?review=r-9", follow_redirects=False)
    assert response.headers["location"] == "/auth/signin?next=%2Freviewer%2F%3Freview%3Dr-9"


def test_a_made_up_or_tampered_cookie_is_not_a_session(env):
    client = env.client_for()
    client.cookies.set(SESSION_COOKIE, "made-up")
    assert client.get("/reviews/queue").status_code == 401
    assert client.get("/queue/", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("path, protected", [
    ("/queue", True), ("/queue/", True), ("/queue/x.js", True), ("/admin/", True),
    ("/queue-ui/reviews", False), ("/admin-ui/roles", False), ("/rules-ui/modules", False), ("/queued", False), ("/health", False),
    ("/auth/signin", False),
])
def test_which_paths_are_pages(path, protected):
    assert is_protected_page(path) is protected


@pytest.mark.parametrize("method, path, status", [
    ("GET", "/reviews/queue", 401), ("GET", "/auth/me", 401), ("POST", "/auth/logout", 303),
    ("GET", "/queue/", 303)])
def test_an_oversized_cookie_reads_as_not_signed_in_not_a_422(env, method, path, status):
    # Found in the close-out review: Cookie(max_length=128) answered 422, so the
    # pages (which redirect on 401) never sent the person to sign in, and
    # signing out failed.
    client = TestClient(app, cookies={SESSION_COOKIE: "x" * 5000})
    assert client.request(method, path, follow_redirects=False).status_code == status


def test_malformed_sign_in_settings_refuse_pages_with_503_not_a_crash(monkeypatch):
    # Found in the close-out review: the page guard is middleware, outside
    # FastAPI's exception handlers, so AuthConfigError became a bare 500.
    from app.auth import dependencies
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "maybe")
    monkeypatch.setattr(dependencies, "_roles", None)
    monkeypatch.setattr(dependencies, "_sessions", None)
    dependencies.get_auth_config.cache_clear()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        page = client.get("/queue/", follow_redirects=False)
        assert page.status_code == 503 and "not configured correctly" in page.text
        assert client.get("/reviews/queue").status_code == 503
    finally:
        dependencies.get_auth_config.cache_clear()


def test_health_and_sign_in_stay_open(env):
    client = env.client_for()
    assert client.get("/health").status_code == 200
    assert client.get("/auth/signin").status_code == 200


# --- signed in ------------------------------------------------------------------------

def test_a_reviewer_reaches_the_review_queue(env):
    client = env.client_for("rita@example.com")
    assert client.get("/queue/").status_code == 200
    assert client.get("/reviews/queue").status_code == 200


# --- 8 hours and sign-out -------------------------------------------------------------

def test_after_eight_hours_pages_and_apis_need_a_new_sign_in(env):
    client = env.client_for("rita@example.com")
    env.clock.now = T0 + timedelta(hours=7, minutes=59)
    assert client.get("/reviews/queue").status_code == 200
    env.clock.now = T0 + timedelta(hours=8)
    assert client.get("/reviews/queue").status_code == 401
    assert client.get("/queue/", follow_redirects=False).status_code == 303


def test_after_sign_out_pages_and_apis_need_a_new_sign_in(env):
    client = env.client_for("rita@example.com")
    token = client.cookies[SESSION_COOKIE]
    client.post("/auth/logout")
    replay = TestClient(app, cookies={SESSION_COOKIE: token})
    assert replay.get("/reviews/queue").status_code == 401
    assert replay.get("/queue/", follow_redirects=False).status_code == 303


def test_someone_removed_is_locked_out_on_their_next_click(env):
    client = env.client_for("rita@example.com")
    env.roles.remove("rita@example.com", BOOT, "c")
    assert client.get("/reviews/queue").status_code == 401


def test_an_unreadable_role_list_refuses_everything_with_503(env):
    client = env.client_for("rita@example.com")
    env.path.write_text("broken", encoding="utf-8")
    assert client.get("/reviews/queue").status_code == 503
    page = client.get("/queue/", follow_redirects=False)
    assert page.status_code == 503 and "Access refused" in page.text


# --- admin-only -------------------------------------------------------------------------

ADMIN_ONLY = [("GET", "/admin-ui/roles", None), ("PUT", "/admin-ui/roles/new@example.com", {"role": "reviewer"}),
              ("DELETE", "/admin-ui/roles/adam@example.com", None),
              ("POST", "/basecamp/comments/process",
               {"comment_id": 1, "message_id": 2, "body": "##Critique##", "created_at": "2026-10-01T09:00:00Z"})]


@pytest.mark.parametrize("method, path, body", ADMIN_ONLY)
def test_a_reviewer_is_refused_admin_only_actions_and_it_is_audited(env, method, path, body):
    response = env.client_for("rita@example.com").request(method, path, json=body)
    assert response.status_code == 403 and response.json()["detail"]["reason_code"] == "ADMIN_ONLY"
    event = env.audit.read_all()[-1]
    assert (event.action, event.actor_id, event.outcome, event.reason_code) == \
        ("admin_action_refused", "rita@example.com", "blocked", "ADMIN_ONLY")
    assert env.roles.role_for("adam@example.com") == "admin"
    assert env.roles.role_for("new@example.com") is None


def test_an_admin_adds_changes_and_removes_reviewers_and_admins(env):
    client = env.client_for("adam@example.com")
    added = client.put("/admin-ui/roles/New@Example.com", json={"role": "reviewer"})
    assert added.status_code == 200 and added.json() == {"email": "new@example.com", "role": "reviewer",
                                                         "result": "added"}
    assert client.put("/admin-ui/roles/new@example.com", json={"role": "admin"}).json()["result"] == "changed"
    assert client.put("/admin-ui/roles/new@example.com", json={"role": "admin"}).json()["result"] == "unchanged"
    assert client.delete("/admin-ui/roles/rita@example.com").json()["result"] == "removed"
    assert client.delete("/admin-ui/roles/rita@example.com").json()["result"] == "not_found"
    listed = client.get("/admin-ui/roles").json()
    assert [(r["email"], r["role"], r["bootstrap"]) for r in listed] == [
        (BOOT, "admin", True), ("adam@example.com", "admin", False), ("new@example.com", "admin", False)]
    changes = [(e.action, e.actor_id, e.subject_id, e.role) for e in env.audit.read_all()[2:]]
    assert changes == [("role_added", "adam@example.com", "new@example.com", "reviewer"),
                       ("role_changed", "adam@example.com", "new@example.com", "admin"),
                       ("role_removed", "adam@example.com", "rita@example.com", "reviewer")]


def test_a_new_admin_can_use_admin_actions_on_their_next_click(env):
    rita = env.client_for("rita@example.com")
    assert rita.get("/admin-ui/roles").status_code == 403
    env.client_for("adam@example.com").put("/admin-ui/roles/rita@example.com", json={"role": "admin"})
    assert rita.get("/admin-ui/roles").status_code == 200


def test_bootstrap_admins_cannot_be_changed_over_http(env):
    response = env.client_for("adam@example.com").delete(f"/admin-ui/roles/{BOOT}")
    assert response.status_code == 409 and response.json()["detail"]["reason_code"] == "BOOTSTRAP_ADMIN"


@pytest.mark.parametrize("bad, status", [("not-an-email", 422), ("a@b", 422)])
def test_a_bad_email_is_refused(env, bad, status):
    response = env.client_for("adam@example.com").put(f"/admin-ui/roles/{bad}", json={"role": "reviewer"})
    assert response.status_code == status


def test_an_unknown_role_is_refused(env):
    response = env.client_for("adam@example.com").put("/admin-ui/roles/x@example.com", json={"role": "owner"})
    assert response.status_code == 422
    assert env.roles.role_for("x@example.com") is None
