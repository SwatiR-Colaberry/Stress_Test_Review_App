import logging

import httpx
import pytest

from app.basecamp.api_client import (
    BasecampAuthError,
    BasecampClient,
    BasecampRateLimited,
    BasecampResponseError,
    BasecampUnavailable,
)
from app.basecamp.config import load_basecamp_config

FAKE_TOKEN = "fake-oauth-token-for-tests-only"
CONFIG = load_basecamp_config({
    "BASECAMP_ACCOUNT_ID": "999999",
    "BASECAMP_ACCESS_TOKEN": FAKE_TOKEN,
    "BASECAMP_USER_AGENT": "Stress Test Review App (tests@example.com)",
})
BASE = "https://3.basecampapi.com/999999"


def make_client(handler, sleeps=None, **kwargs):
    sleeps = [] if sleeps is None else sleeps
    return BasecampClient(CONFIG, transport=httpx.MockTransport(handler), sleep=sleeps.append, **kwargs)


def scripted(*responses):
    """Handler that returns the given responses in order and records requests."""
    queue = list(responses)
    seen = []

    def handler(request):
        seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    handler.seen = seen
    return handler


def test_sends_oauth_bearer_token_user_agent_and_returns_json():
    handler = scripted(httpx.Response(200, json={"id": 1}))
    assert make_client(handler).get_json("/projects/1.json") == {"id": 1}
    request = handler.seen[0]
    assert str(request.url) == f"{BASE}/projects/1.json"
    assert request.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert request.headers["User-Agent"].startswith("Stress Test Review App")


def test_follows_link_next_pagination():
    handler = scripted(
        httpx.Response(200, json=[{"id": 1}], headers={"Link": f'<{BASE}/x.json?page=2>; rel="next"'}),
        httpx.Response(200, json=[{"id": 2}]),
    )
    assert make_client(handler).get_all("/x.json") == [{"id": 1}, {"id": 2}]
    assert str(handler.seen[1].url) == f"{BASE}/x.json?page=2"


def test_empty_list_returns_empty():
    assert make_client(scripted(httpx.Response(200, json=[]))).get_all("/x.json") == []


def test_pagination_link_to_another_host_is_refused_so_the_token_is_not_leaked():
    handler = scripted(httpx.Response(200, json=[], headers={"Link": '<https://evil.example/x>; rel="next"'}))
    with pytest.raises(BasecampResponseError):
        make_client(handler).get_all("/x.json")
    assert len(handler.seen) == 1


def test_pagination_link_over_plain_http_is_refused_even_on_the_same_host():
    handler = scripted(httpx.Response(200, json=[], headers={"Link": '<http://3.basecampapi.com/999999/x.json?page=2>; rel="next"'}))
    with pytest.raises(BasecampResponseError, match="https"):
        make_client(handler).get_all("/x.json")
    assert len(handler.seen) == 1


def test_redirects_are_not_followed():
    handler = scripted(httpx.Response(302, headers={"Location": "https://elsewhere.example/"}))
    with pytest.raises(BasecampResponseError):
        make_client(handler).get_json("/a.json")
    assert len(handler.seen) == 1


def test_page_cap_stops_an_endless_pagination_loop():
    def handler(request):
        return httpx.Response(200, json=[{"id": 1}], headers={"Link": f'<{BASE}/x.json?p=n>; rel="next"'})

    with pytest.raises(BasecampResponseError, match="pages"):
        make_client(handler, max_pages=3).get_all("/x.json")


# --- Failure path: rate limits exceeded ---

def test_429_waits_retry_after_then_succeeds():
    sleeps = []
    handler = scripted(httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={"ok": True}))
    assert make_client(handler, sleeps).get_json("/a.json") == {"ok": True}
    assert sleeps == [7.0]


def test_retry_after_is_capped():
    sleeps = []
    handler = scripted(httpx.Response(429, headers={"Retry-After": "3600"}), httpx.Response(200, json={}))
    make_client(handler, sleeps).get_json("/a.json")
    assert sleeps == [30.0]


def test_429_on_every_attempt_raises_rate_limited_after_three_attempts():
    handler = scripted(*[httpx.Response(429) for _ in range(3)])
    with pytest.raises(BasecampRateLimited) as exc:
        make_client(handler).get_json("/a.json")
    assert exc.value.status_code == 429
    assert len(handler.seen) == 3


# --- Failure path: invalid OAuth token ---

@pytest.mark.parametrize("status", [401, 403])
def test_invalid_token_raises_auth_error_without_retrying(status):
    sleeps = []
    handler = scripted(httpx.Response(status))
    with pytest.raises(BasecampAuthError):
        make_client(handler, sleeps).get_json("/a.json")
    assert len(handler.seen) == 1 and sleeps == []


# --- Failure path: network failure ---

def test_network_error_then_success_retries_with_backoff():
    sleeps = []
    handler = scripted(httpx.ConnectError("down"), httpx.ReadTimeout("slow"), httpx.Response(200, json={"ok": 1}))
    assert make_client(handler, sleeps).get_json("/a.json") == {"ok": 1}
    assert sleeps == [1.0, 2.0]


def test_network_failure_on_every_attempt_raises_unavailable_after_three_attempts():
    handler = scripted(*[httpx.ConnectError("down") for _ in range(3)])
    with pytest.raises(BasecampUnavailable):
        make_client(handler).get_json("/a.json")
    assert len(handler.seen) == 3


def test_5xx_on_every_attempt_raises_unavailable():
    handler = scripted(*[httpx.Response(503) for _ in range(3)])
    with pytest.raises(BasecampUnavailable) as exc:
        make_client(handler).get_json("/a.json")
    assert exc.value.status_code == 503


def test_other_4xx_is_not_retried():
    handler = scripted(httpx.Response(404))
    with pytest.raises(BasecampResponseError) as exc:
        make_client(handler).get_json("/a.json")
    assert exc.value.status_code == 404 and len(handler.seen) == 1


def test_non_json_body_raises_response_error():
    with pytest.raises(BasecampResponseError, match="JSON"):
        make_client(scripted(httpx.Response(200, text="<html>"))).get_json("/a.json")


def test_logs_never_contain_the_token_or_query_string(caplog):
    caplog.set_level(logging.INFO, logger="stress_test_review.basecamp_api")
    handler = scripted(httpx.Response(401))
    with pytest.raises(BasecampAuthError):
        make_client(handler).get_json("/a.json?secret=q")
    assert caplog.records
    assert FAKE_TOKEN not in caplog.text
    assert "secret=q" not in caplog.text
    assert '"error_class": "AuthError"' in caplog.text


# --- POST (STORY-006): retried only when the request never reached Basecamp ---

COMMENTS = "/buckets/1/recordings/2/comments.json"


def test_post_sends_json_body_and_returns_the_created_comment():
    handler = scripted(httpx.Response(201, json={"id": 77}))
    created = make_client(handler).post_json(COMMENTS, {"content": "<div>Feedback</div>"})
    assert created == {"id": 77}
    request = handler.seen[0]
    assert request.method == "POST"
    assert str(request.url) == f"{BASE}{COMMENTS}"
    assert request.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert request.read() == b'{"content":"<div>Feedback</div>"}'


def test_post_connection_error_is_retried_because_nothing_was_sent():
    sleeps = []
    handler = scripted(httpx.ConnectError("refused"), httpx.Response(201, json={"id": 77}))
    assert make_client(handler, sleeps).post_json(COMMENTS, {"content": "x"}) == {"id": 77}
    assert len(handler.seen) == 2
    assert sleeps == [1.0]


def test_post_connection_error_on_every_attempt_raises_unavailable_after_three_attempts():
    handler = scripted(*[httpx.ConnectError("refused")] * 3)
    with pytest.raises(BasecampUnavailable):
        make_client(handler).post_json(COMMENTS, {"content": "x"})
    assert len(handler.seen) == 3


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("dropped")])
def test_post_with_no_answer_is_not_retried_because_it_may_have_been_posted(error):
    handler = scripted(error, httpx.Response(201, json={"id": 77}))
    with pytest.raises(BasecampUnavailable, match="may have been applied"):
        make_client(handler).post_json(COMMENTS, {"content": "x"})
    assert len(handler.seen) == 1


def test_post_5xx_is_not_retried():
    handler = scripted(httpx.Response(502), httpx.Response(201, json={"id": 77}))
    with pytest.raises(BasecampUnavailable) as caught:
        make_client(handler).post_json(COMMENTS, {"content": "x"})
    assert caught.value.status_code == 502
    assert len(handler.seen) == 1


def test_post_429_waits_and_retries_because_basecamp_refused_it():
    sleeps = []
    handler = scripted(httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(201, json={"id": 77}))
    assert make_client(handler, sleeps).post_json(COMMENTS, {"content": "x"}) == {"id": 77}
    assert sleeps == [3.0]


@pytest.mark.parametrize("status", [401, 403])
def test_post_invalid_token_is_never_retried(status):
    handler = scripted(httpx.Response(status), httpx.Response(201, json={"id": 77}))
    with pytest.raises(BasecampAuthError):
        make_client(handler).post_json(COMMENTS, {"content": "x"})
    assert len(handler.seen) == 1


def test_post_rejected_body_is_a_contract_error_not_retried():
    handler = scripted(httpx.Response(422, json={"error": "content missing"}))
    with pytest.raises(BasecampResponseError) as caught:
        make_client(handler).post_json(COMMENTS, {"content": ""})
    assert caught.value.status_code == 422
    assert len(handler.seen) == 1


@pytest.mark.parametrize("body", [b"[]", b"not json"])
def test_post_success_that_is_not_a_json_object_is_a_contract_error(body):
    handler = scripted(httpx.Response(201, content=body))
    with pytest.raises(BasecampResponseError):
        make_client(handler).post_json(COMMENTS, {"content": "x"})


def test_post_logs_method_and_never_the_body_or_token(caplog):
    caplog.set_level(logging.INFO, logger="stress_test_review.basecamp_api")
    handler = scripted(httpx.ConnectError("refused"), httpx.Response(201, json={"id": 77}))
    make_client(handler).post_json(COMMENTS, {"content": "Private feedback text"})
    assert '"method": "POST"' in caplog.text
    assert "Private feedback text" not in caplog.text
    assert FAKE_TOKEN not in caplog.text
