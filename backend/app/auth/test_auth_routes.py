"""Sign in with Basecamp, end to end through the FastAPI app (STORY-014).

A fake Launchpad (app/auth/fake.py) stands in for Basecamp; nothing here
reaches the real one.
"""
import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.audit.dependencies import get_audit_trail
from app.audit.trail import InMemoryAuditTrail
from app.auth import fake
from app.auth.dependencies import get_auth_config, get_launchpad_client, get_role_store, get_session_store
from app.auth.roles import RoleStore
from app.auth.sessions import SessionStore
from app.main import app
from app.auth.sessions import SESSION_COOKIE
from app.routers.auth import STATE_COOKIE

BOOT = "boss@example.com"


@pytest.fixture
def env(tmp_path):
    audit = InMemoryAuditTrail()
    config = fake.fake_config()
    roles = RoleStore(tmp_path / "roles.json", config.bootstrap_admin_emails, audit)
    roles.set_role("rita@example.com", "reviewer", BOOT, "setup")
    roles.set_role("adam@example.com", "admin", BOOT, "setup")
    sessions = SessionStore(roles)
    launchpad = fake.FakeLaunchpad()
    launchpad.add("code-rita", "Rita@Example.com", "Rita")
    launchpad.add("code-adam", "adam@example.com", "Adam")
    launchpad.add("code-boss", BOOT, "Boss")
    launchpad.add("code-olga", "olga@example.com", "Olga")
    launchpad.add("code-other", "rita@example.com", accounts=(123,))
    state = {"config": config}
    app.dependency_overrides.update({
        get_audit_trail: lambda: audit, get_auth_config: lambda: state["config"],
        get_role_store: lambda: roles, get_session_store: lambda: sessions,
        get_launchpad_client: lambda: launchpad.client(state["config"]),
    })
    yield type("Env", (), dict(audit=audit, roles=roles, sessions=sessions, launchpad=launchpad, state=state,
                               client=TestClient(app)))
    app.dependency_overrides.clear()


def sign_in(env, code, next_path=None):
    client = env.client
    params = {"next": next_path} if next_path else {}
    start = client.get("/auth/login", params=params, follow_redirects=False)
    assert start.status_code == 303
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return client.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)


def sign_in_events(env):
    return [e for e in env.audit.read_all() if e.action in ("signed_in", "sign_in_refused", "signed_out")]


# --- happy paths -----------------------------------------------------------------

def test_login_sends_the_browser_to_basecamp_with_a_state(env):
    response = env.client.get("/auth/login", follow_redirects=False)
    target = urlparse(response.headers["location"])
    query = parse_qs(target.query)
    assert target.netloc == "launchpad.37signals.com" and target.path == "/authorization/new"
    assert query["client_id"] == ["fake-client"] and query["type"] == ["web_server"]
    assert query["redirect_uri"] == ["http://localhost:8000/auth/callback"]
    assert query["state"][0] == response.cookies[STATE_COOKIE]
    assert "httponly" in response.headers["set-cookie"].lower()


def test_a_reviewer_signs_in_and_reaches_the_review_queue_as_a_reviewer(env):
    response = sign_in(env, "code-rita")
    assert response.status_code == 303 and response.headers["location"] == "/queue/"
    cookie = [h for h in response.headers.get_list("set-cookie") if h.startswith(SESSION_COOKIE + "=")][0].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "max-age=28800" in cookie
    me = env.client.get("/auth/me").json()
    assert (me["email"], me["name"], me["role"]) == ("rita@example.com", "Rita Person", "reviewer")


def test_an_admin_signs_in_as_an_admin(env):
    sign_in(env, "code-adam")
    assert env.client.get("/auth/me").json()["role"] == "admin"


def test_a_bootstrap_admin_signs_in_as_an_admin(env):
    sign_in(env, "code-boss")
    assert env.client.get("/auth/me").json()["role"] == "admin"


def test_sign_in_returns_to_the_page_the_person_asked_for(env):
    assert sign_in(env, "code-rita", "/reviewer/?review=r1").headers["location"] == "/reviewer/?review=r1"


@pytest.mark.parametrize("bad_next", ["//evil.example/x", "https://evil.example", "/\\evil.example", "queue"])
def test_sign_in_never_redirects_off_site(env, bad_next):
    assert sign_in(env, "code-rita", bad_next).headers["location"] == "/queue/"


def test_a_sign_in_is_audited_with_who_role_and_when(env):
    sign_in(env, "code-rita")
    (event,) = sign_in_events(env)
    assert (event.action, event.actor_id, event.role, event.outcome) == \
        ("signed_in", "rita@example.com", "reviewer", "success")
    assert event.recorded_at.tzinfo is not None


# --- refusals --------------------------------------------------------------------

def test_someone_on_neither_list_is_refused_with_a_clear_message(env):
    response = sign_in(env, "code-olga")
    assert response.status_code == 403
    assert "Access refused" in response.text
    assert "olga@example.com" in response.text and "not on the reviewer or admin list" in response.text
    assert SESSION_COOKIE not in response.cookies
    assert env.client.get("/auth/me").status_code == 401
    (event,) = sign_in_events(env)
    assert (event.action, event.actor_id, event.reason_code, event.outcome) == \
        ("sign_in_refused", "olga@example.com", "NOT_ON_LIST", "blocked")


def test_someone_outside_our_basecamp_account_is_refused(env):
    response = sign_in(env, "code-other")
    assert response.status_code == 403 and "not a member of the Basecamp account" in response.text
    assert sign_in_events(env)[0].reason_code == "NOT_IN_ACCOUNT"


def test_a_wrong_state_is_refused_before_basecamp_is_asked(env):
    env.client.get("/auth/login", follow_redirects=False)
    response = env.client.get("/auth/callback", params={"code": "code-rita", "state": "forged"})
    assert response.status_code == 400 and "expired" in response.text
    assert env.launchpad.requests == []
    assert sign_in_events(env)[0].reason_code == "STATE_MISMATCH"


def test_a_callback_without_the_state_cookie_is_refused(env):
    response = TestClient(app).get("/auth/callback", params={"code": "code-rita", "state": "anything"})
    assert response.status_code == 400
    assert env.launchpad.requests == []


def test_the_state_works_only_once(env):
    start = env.client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    env.client.get("/auth/callback", params={"code": "code-rita", "state": state}, follow_redirects=False)
    env.client.cookies.delete(SESSION_COOKIE)
    again = env.client.get("/auth/callback", params={"code": "code-rita", "state": state}, follow_redirects=False)
    assert again.status_code == 400


def test_cancelling_in_basecamp_is_refused(env):
    start = env.client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    response = env.client.get("/auth/callback", params={"error": "access_denied", "state": state})
    assert response.status_code == 403 and "cancelled" in response.text
    assert sign_in_events(env)[0].reason_code == "BASECAMP_DENIED"


@pytest.mark.parametrize("break_it", [
    lambda lp: setattr(lp, "token_status", 401),
    lambda lp: setattr(lp, "identity_status", 503),
    lambda lp: setattr(lp, "identity_body", {"unexpected": True}),
    lambda lp: setattr(lp, "identity_body", {"identity": {"email_address": "not-an-email"}, "accounts": []}),
])
def test_basecamp_failing_is_refused_with_a_try_again_message(env, break_it):
    break_it(env.launchpad)
    response = sign_in(env, "code-rita")
    assert response.status_code == 502 and "try again" in response.text
    assert sign_in_events(env)[0].reason_code == "BASECAMP_ERROR"
    assert SESSION_COOKIE not in response.cookies


def test_basecamp_5xx_is_retried_three_times_then_refused(env):
    env.launchpad.identity_status = 503
    sign_in(env, "code-rita")
    assert sum(r.url.path == "/authorization.json" for r in env.launchpad.requests) == 3


def test_an_unconfigured_server_refuses_sign_in_clearly(env):
    env.state["config"] = fake.fake_config(client_id="", client_secret="")
    response = env.client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 503 and "not set up" in response.text
    callback = env.client.get("/auth/callback", params={"code": "code-rita", "state": "s"})
    assert callback.status_code == 503 and env.launchpad.requests == []


def test_an_unreadable_role_list_refuses_everyone_but_bootstrap_admins(env, tmp_path):
    (tmp_path / "roles.json").write_text("broken", encoding="utf-8")
    assert sign_in(env, "code-rita").status_code == 503
    assert sign_in_events(env)[0].reason_code == "ROLE_LIST_UNAVAILABLE"
    assert sign_in(env, "code-boss").status_code == 303


def test_a_sign_in_that_cannot_be_audited_is_not_completed(env):
    class Failing(InMemoryAuditTrail):
        def record(self, event):
            from app.audit.trail import AuditWriteError
            raise AuditWriteError("disk full")
    app.dependency_overrides[get_audit_trail] = lambda: Failing()
    response = sign_in(env, "code-rita")
    assert response.status_code == 503 and SESSION_COOKIE not in response.cookies


# --- me and sign-out --------------------------------------------------------------

def test_me_without_a_session_is_401(env):
    response = env.client.get("/auth/me")
    assert response.status_code == 401 and response.json()["detail"]["reason_code"] == "NOT_SIGNED_IN"


def test_sign_out_ends_the_session_and_is_audited(env):
    sign_in(env, "code-rita")
    response = env.client.post("/auth/logout", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/auth/signin?signed_out=1"
    assert env.client.get("/auth/me").status_code == 401
    assert [e.action for e in sign_in_events(env)] == ["signed_in", "signed_out"]
    assert sign_in_events(env)[1].actor_id == "rita@example.com"


def test_the_old_cookie_does_not_work_after_sign_out(env):
    sign_in(env, "code-rita")
    token = env.client.cookies[SESSION_COOKIE]
    env.client.post("/auth/logout")
    assert TestClient(app, cookies={SESSION_COOKIE: token}).get("/auth/me").status_code == 401


def test_signing_out_twice_is_harmless_and_audited_once(env):
    sign_in(env, "code-rita")
    token = env.client.cookies[SESSION_COOKIE]
    env.client.post("/auth/logout")
    TestClient(app, cookies={SESSION_COOKIE: token}).post("/auth/logout")
    assert [e.action for e in sign_in_events(env)].count("signed_out") == 1


def test_the_sign_in_page_offers_basecamp_and_says_when_signed_out(env):
    page = env.client.get("/auth/signin", params={"signed_out": "1", "next": "/rules/"}).text
    assert "Sign in with Basecamp" in page and "You have signed out." in page
    assert 'href="/auth/login?next=%2Frules%2F"' in page


# --- nothing secret leaks ---------------------------------------------------------

def test_no_token_code_or_secret_appears_in_logs_audit_or_pages(env, caplog):
    pages = [sign_in(env, "code-rita").text]
    session_token = env.client.cookies[SESSION_COOKIE]
    pages += [env.client.get("/auth/me").text, sign_in(env, "code-olga").text, env.client.post("/auth/logout").text]
    forbidden = [fake.FAKE_ACCESS_TOKEN, fake.FAKE_REFRESH_TOKEN, fake.FAKE_CLIENT_SECRET, "code-rita", "code-olga",
                 session_token]
    audit_text = json.dumps([e.model_dump(mode="json") for e in env.audit.read_all()])
    logs = "\n".join(r.getMessage() for r in caplog.records)
    for secret in forbidden:
        assert secret not in audit_text and secret not in logs and all(secret not in p for p in pages)
    assert "@" not in logs  # emails stay in the git-ignored audit trail only
