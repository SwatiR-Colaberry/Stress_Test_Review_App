"""signin_demo.py (STORY-014): the demo chooser leads through the real
sign-in code to each outcome; nothing touches data/ or the real Basecamp."""
import re
import sys
from html import unescape
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.audit.dependencies import get_audit_trail
from app.main import app

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signin_demo  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_TRAIL_PATH", str(tmp_path / "audit.jsonl"))
    routes_before = list(app.router.routes)
    shared = get_audit_trail()  # as in the real demo: routes and role list write one trail
    app.dependency_overrides[get_audit_trail] = lambda: shared
    signin_demo.install(app, tmp_path, "http://testserver")
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.router.routes[:] = routes_before  # the demo-only page leaves with the demo


def _choose(client, label_start):
    start = client.get("/auth/login?next=/queue/", follow_redirects=False)
    assert start.headers["location"].startswith("/demo-launchpad?state=")
    chooser = client.get(start.headers["location"]).text
    href = next(unescape(h) for h, label in re.findall(r'<a href="([^"]+)">([^<]+)</a>', chooser)
                if label.startswith(label_start))
    return client.get(href, follow_redirects=False)


def test_the_demo_reviewer_reaches_the_queue_as_a_reviewer(client):
    response = _choose(client, "Demo Reviewer")
    assert response.status_code == 303 and response.headers["location"] == "/queue/"
    assert client.get("/auth/me").json()["role"] == "reviewer"
    assert client.get("/admin-ui/roles").status_code == 403


def test_the_demo_admin_can_manage_roles(client):
    _choose(client, "Demo Admin")
    assert client.put("/admin-ui/roles/new@example.com", json={"role": "reviewer"}).json()["result"] == "added"


@pytest.mark.parametrize("who", ["Olga Outsider", "Pat Partner", "Cancel"])
def test_everyone_else_is_refused_with_a_clear_message(client, who):
    response = _choose(client, who)
    assert response.status_code == 403 and "Access refused" in response.text


def test_the_demo_records_sign_ins_in_the_audit_trail(client):
    _choose(client, "Demo Reviewer")
    _choose(client, "Olga")
    actions = [e.action for e in get_audit_trail().read_all()]
    assert actions[-2:] == ["signed_in", "sign_in_refused"]
