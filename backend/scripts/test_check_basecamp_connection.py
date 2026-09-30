import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_basecamp_connection  # noqa: E402

ENV = {"BASECAMP_ACCOUNT_ID": "999999", "BASECAMP_ACCESS_TOKEN": "fake-token-not-real",
       "BASECAMP_USER_AGENT": "Stress Test Review App (tests@example.com)"}


@pytest.fixture(autouse=True)
def fake_env(monkeypatch):
    monkeypatch.setattr(check_basecamp_connection, "load_dotenv", lambda *a, **k: None)  # never read the real .env
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


def run(capsys, response, project_id="111"):
    transport = httpx.MockTransport(lambda request: response)
    code = check_basecamp_connection.main(["--project-id", project_id], transport=transport)
    return code, capsys.readouterr().out


def test_connected_prints_counts_only(capsys):
    dock = [{"name": "message_board", "id": 1, "title": "Private board title"}, {"name": "message_board", "id": 2},
            {"name": "chat", "id": 3}]
    code, out = run(capsys, httpx.Response(200, json={"id": 111, "name": "Secret project", "dock": dock}))
    assert code == 0
    assert "message boards in this project: 2" in out
    assert "Secret project" not in out and "Private board title" not in out and "fake-token" not in out


@pytest.mark.parametrize("response, code", [
    (httpx.Response(401), 2),
    (httpx.Response(503), 3),
    (httpx.Response(404), 4),
    (httpx.Response(200, json={"id": 111}), 4),
])
def test_failures_have_their_own_exit_code(capsys, response, code):
    assert run(capsys, response)[0] == code


def test_missing_settings_name_the_variable(capsys, monkeypatch):
    monkeypatch.delenv("BASECAMP_ACCESS_TOKEN")
    code, out = run(capsys, httpx.Response(200, json={"dock": []}))
    assert code == 1 and "BASECAMP_ACCESS_TOKEN" in out
