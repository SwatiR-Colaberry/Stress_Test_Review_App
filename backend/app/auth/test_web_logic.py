"""The signed-in bar and Admins page: pure JavaScript logic (run in Node,
skipped where Node is absent; GitHub's ubuntu runners include it) and the
pages being served only to signed-in people (STORY-014)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.auth.fake import signed_in_client
from app.main import app

SESSION_LOGIC = Path(__file__).parents[1] / "human_review" / "web" / "session_logic.js"
ADMIN_LOGIC = Path(__file__).parent / "web" / "admin_logic.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _js(logic, expression):
    script = (f"const L = require({json.dumps(str(logic))});"
              f"process.stdout.write(JSON.stringify({expression}));")
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=10, check=True)
    return json.loads(out.stdout)


@needs_node
def test_an_ended_session_comes_back_to_the_same_page():
    assert _js(SESSION_LOGIC, "L.signInUrl('/reviewer/?review=r-1', true)") == \
        "/auth/signin?expired=1&next=%2Freviewer%2F%3Freview%3Dr-1"
    assert _js(SESSION_LOGIC, "L.signInUrl('/queue/', false)") == "/auth/signin?next=%2Fqueue%2F"


@needs_node
@pytest.mark.parametrize("bad", ["'https://evil.example/'", "''", "null"])
def test_sign_in_never_returns_to_another_site(bad):
    assert _js(SESSION_LOGIC, f"L.signInUrl({bad}, true)") == "/auth/signin?expired=1&next=%2Fqueue%2F"


@needs_node
def test_sign_in_refusals_are_in_plain_words():
    assert "Sign in again" in _js(SESSION_LOGIC, "L.explainAuthFailure(401, null)")
    assert "Only an admin" in _js(SESSION_LOGIC, "L.explainAuthFailure(403, {detail: {reason_code: 'ADMIN_ONLY'}})")
    assert "cannot be read" in _js(SESSION_LOGIC,
                                   "L.explainAuthFailure(503, {detail: {reason_code: 'ROLE_LIST_UNAVAILABLE'}})")
    assert _js(SESSION_LOGIC, "L.explainAuthFailure(404, {detail: {reason_code: 'REVIEW_NOT_FOUND'}})") is None
    assert _js(SESSION_LOGIC, "[L.roleLabel('admin'), L.roleLabel('reviewer'), L.roleLabel('x')]") == \
        ["Admin", "Reviewer", ""]


@needs_node
def test_role_refusals_are_in_plain_words():
    assert "last admin" in _js(ADMIN_LOGIC, "L.explainRoleFailure(409, {detail: {reason_code: 'LAST_ADMIN'}})")
    assert "server configuration" in _js(ADMIN_LOGIC,
                                         "L.explainRoleFailure(409, {detail: {reason_code: 'BOOTSTRAP_ADMIN'}})")
    assert "valid email" in _js(ADMIN_LOGIC, "L.explainRoleFailure(422, {detail: [{}]})")
    assert "Nothing changed" in _js(ADMIN_LOGIC, "L.explainRoleFailure(503, null)")
    assert "reload to check" in _js(ADMIN_LOGIC, "L.explainRoleFailure(0, null, true)")


@needs_node
def test_each_change_is_described():
    def said(change):
        return _js(ADMIN_LOGIC, f"L.describeChange({json.dumps(change)})")
    assert said({"email": "a@x.com", "role": "reviewer", "result": "added"}) == "a@x.com was added as a reviewer."
    assert said({"email": "a@x.com", "role": "admin", "result": "changed"}) == "a@x.com is now an admin."
    assert "nothing changed" in said({"email": "a@x.com", "role": "admin", "result": "unchanged"})
    assert "can no longer sign in" in said({"email": "a@x.com", "result": "removed"})


@needs_node
@pytest.mark.parametrize("script", sorted((Path(__file__).parents[1]).glob("*/web/*.js")), ids=lambda p: p.name)
def test_every_page_script_is_valid_javascript(script):
    subprocess.run([NODE, "--check", str(script)], check=True, timeout=10)


def test_every_page_shows_the_signed_in_bar_and_no_reviewer_id_box():
    client = signed_in_client(app)
    for page in ("/queue/", "/reviewer/", "/rules/", "/admin/"):
        html = client.get(page).text
        assert 'id="who"' in html and "session.js" in html, page
        assert "reviewer-id" not in html and "Reviewer id" not in html, page
    for script in ("/reviewer/session.js", "/reviewer/session_logic.js", "/admin/admin.js", "/admin/admin_logic.js",
                   "/admin/admin.css"):
        assert client.get(script).status_code == 200, script


def test_no_page_script_sends_a_reviewer_id_header():
    for script in (Path(__file__).parents[1]).glob("*/web/*.js"):
        assert "X-Reviewer-Id" not in script.read_text(encoding="utf-8"), script.name


def test_a_reviewer_can_open_the_admin_page_but_its_api_refuses_them():
    client = signed_in_client(app, "rita@example.com", "reviewer")
    assert client.get("/admin/").status_code == 200  # the page itself holds no data
    response = client.get("/admin-ui/roles")
    assert response.status_code == 403 and response.json()["detail"]["reason_code"] == "ADMIN_ONLY"
