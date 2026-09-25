import socket
import stat
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import SecretStr

from app.basecamp import oauth

SECRET = SecretStr("fake-client-secret-for-tests")
TOKENS = {"access_token": "fake-access-for-tests", "refresh_token": "fake-refresh-for-tests", "expires_in": 1209600}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_authorize_url_uses_web_server_flow_with_state():
    url = urlparse(oauth.authorize_url("cid", "http://localhost:8765/cb", "st4te"))
    q = parse_qs(url.query)
    assert url.netloc == "launchpad.37signals.com" and url.path == "/authorization/new"
    assert q == {"type": ["web_server"], "client_id": ["cid"], "redirect_uri": ["http://localhost:8765/cb"], "state": ["st4te"]}


@pytest.mark.parametrize("uri", ["https://localhost:1/cb", "http://example.com:80/cb", "http://localhost/cb"])
def test_non_local_redirect_uris_are_rejected(uri):
    with pytest.raises(oauth.OAuthError):
        oauth.check_redirect_uri(uri)


def call_back_later(url):
    def go():
        for _ in range(50):
            try:
                httpx.get(url, timeout=2)
                return
            except httpx.ConnectError:
                time.sleep(0.05)
    threading.Thread(target=go, daemon=True).start()


def test_callback_listener_returns_the_code_when_state_matches():
    uri = f"http://127.0.0.1:{free_port()}/cb"
    call_back_later(f"{uri}?code=abc123&state=good")
    assert oauth.wait_for_callback(uri, "good", timeout_s=10) == "abc123"


def test_callback_with_wrong_state_is_rejected():
    uri = f"http://127.0.0.1:{free_port()}/cb"
    call_back_later(f"{uri}?code=abc123&state=forged")
    with pytest.raises(oauth.OAuthError, match="State mismatch"):
        oauth.wait_for_callback(uri, "good", timeout_s=10)


def test_callback_with_access_denied_is_reported():
    uri = f"http://127.0.0.1:{free_port()}/cb"
    call_back_later(f"{uri}?error=access_denied&state=good")
    with pytest.raises(oauth.OAuthError, match="access_denied"):
        oauth.wait_for_callback(uri, "good", timeout_s=10)


def test_callback_times_out_when_nobody_authorizes():
    with pytest.raises(oauth.OAuthError, match="within"):
        oauth.wait_for_callback(f"http://127.0.0.1:{free_port()}/cb", "good", timeout_s=1)


def test_exchange_code_posts_form_and_returns_secret_tokens():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=TOKENS)

    tokens = oauth.exchange_code("cid", SECRET, "http://localhost:1/cb", "the-code", transport=httpx.MockTransport(handler))
    assert tokens.access_token.get_secret_value() == "fake-access-for-tests"
    assert "fake-access-for-tests" not in repr(tokens)
    form = parse_qs(seen[0].content.decode())
    assert form["type"] == ["web_server"] and form["code"] == ["the-code"]
    assert "client_secret" not in str(seen[0].url)  # secret is in the body, not the URL


def test_exchange_retries_only_when_the_connection_never_opened():
    calls, sleeps = [], []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json=TOKENS)

    oauth.exchange_code("cid", SECRET, "u", "c", transport=httpx.MockTransport(handler), sleep=sleeps.append)
    assert len(calls) == 3 and sleeps == [1.0, 2.0]


def test_exchange_is_not_retried_after_a_read_timeout_because_the_code_may_be_spent():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(oauth.OAuthError, match="run the script again"):
        oauth.exchange_code("cid", SECRET, "u", "c", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert len(calls) == 1


def test_refused_exchange_reports_status_without_secrets():
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "invalid_client"}))
    with pytest.raises(oauth.OAuthError) as exc:
        oauth.exchange_code("cid", SECRET, "u", "the-code", transport=transport)
    assert "401" in str(exc.value) and "invalid_client" in str(exc.value)
    assert "fake-client-secret" not in str(exc.value) and "the-code" not in str(exc.value)


def test_fetch_accounts_keeps_only_basecamp_accounts():
    body = {"accounts": [{"product": "bc3", "id": 111, "name": "Colaberry"},
                         {"product": "hey", "id": 222, "name": "Mail"},
                         {"product": "bcx", "id": 333, "name": "Old Basecamp 2"}]}
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    accounts = oauth.fetch_basecamp_accounts(SecretStr("t"), "UA", transport=transport)
    assert [(a.id, a.name) for a in accounts] == [(111, "Colaberry")]


def test_fetch_accounts_gives_up_after_three_5xx():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(502)

    with pytest.raises(oauth.OAuthError):
        oauth.fetch_basecamp_accounts(SecretStr("t"), "UA", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert len(calls) == 3


def test_update_env_file_replaces_and_appends_keeps_other_lines_and_is_owner_only(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DB_SERVER=x\nBASECAMP_ACCESS_TOKEN=old\n# comment\n")
    updates = {"BASECAMP_ACCESS_TOKEN": "new", "BASECAMP_ACCOUNT_ID": "111"}
    oauth.update_env_file(env, updates)
    oauth.update_env_file(env, updates)  # re-run: same result, no duplicate lines
    assert env.read_text() == 'DB_SERVER=x\nBASECAMP_ACCESS_TOKEN="new"\n# comment\nBASECAMP_ACCOUNT_ID="111"\n'
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert not (tmp_path / ".env.tmp").exists()


@pytest.mark.parametrize("updates", [{"DB_PASSWORD": "x"}, {"BASECAMP_ACCESS_TOKEN": 'a"b'}, {"BASECAMP_ACCESS_TOKEN": "a\nX=1"}])
def test_update_env_file_refuses_foreign_keys_and_injection(tmp_path, updates):
    with pytest.raises(oauth.OAuthError):
        oauth.update_env_file(tmp_path / ".env", updates)
