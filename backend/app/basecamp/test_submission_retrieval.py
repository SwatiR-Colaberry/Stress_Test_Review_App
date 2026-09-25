import json
import logging

import httpx
import pytest

from app.basecamp.api_client import BasecampAuthError, BasecampClient, BasecampRateLimited, BasecampResponseError, BasecampUnavailable
from app.basecamp.config import load_basecamp_config
from app.audit.trail import AuditWriteError, InMemoryAuditTrail
from app.basecamp.submission_retrieval import retrieve_project_submissions

FAKE_TOKEN = "fake-oauth-token-for-tests-only"
CONFIG = load_basecamp_config({
    "BASECAMP_ACCOUNT_ID": "999999",
    "BASECAMP_ACCESS_TOKEN": FAKE_TOKEN,
    "BASECAMP_USER_AGENT": "Stress Test Review App (tests@example.com)",
})
P = "/999999"
PROJECT = 100
BOARD = 200
REVIEWER = "reviewer-42"

MESSAGE = {
    "id": 301, "subject": "Stress Test 0 - Sales Forecasting", "created_at": "2026-09-20T10:00:00Z",
    "creator": {"id": 7, "name": "Student"},
    "content": '<div>Dataset: <a href="https://kaggle.com/d/sales">here</a>'
               '<bc-attachment content-type="application/pdf" filename="st0.pdf" url="https://3.basecamp.com/b/st0.pdf"></bc-attachment></div>',
}
COMMENT = {
    "id": 401, "created_at": "2026-09-21T09:00:00Z", "creator": {"id": 7},
    "content": '<div>Updated V2 <a href="https://github.com/s/repo">repo</a>'
               '<bc-attachment content-type="image/png" filename="chart.png" url="https://3.basecamp.com/b/chart.png"></bc-attachment> ##Critique##</div>',
}


def project_with_board(enabled=True):
    return {"id": PROJECT, "dock": [
        {"name": "todoset", "id": 1, "enabled": True},
        {"name": "message_board", "id": BOARD, "enabled": enabled},
    ]}


def fake_basecamp(routes):
    """routes: path -> Response or callable(request) -> Response. Unknown paths 404."""
    calls = []

    def handler(request):
        calls.append(request.url.path)
        route = routes.get(request.url.path)
        if route is None:
            return httpx.Response(404)
        return route(request) if callable(route) else route

    handler.calls = calls
    return handler


def client_for(handler):
    return BasecampClient(CONFIG, transport=httpx.MockTransport(handler), sleep=lambda s: None)


def full_project_routes():
    return {
        f"{P}/projects/{PROJECT}.json": httpx.Response(200, json=project_with_board()),
        f"{P}/buckets/{PROJECT}/message_boards/{BOARD}/messages.json": httpx.Response(200, json=[MESSAGE]),
        f"{P}/buckets/{PROJECT}/recordings/301/comments.json": httpx.Response(200, json=[COMMENT]),
    }


# --- AC1: a project with submissions includes comments, attachments and links ---

def test_project_with_submissions_includes_comments_attachments_and_links():
    dataset = retrieve_project_submissions(client_for(fake_basecamp(full_project_routes())), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    assert dataset.project_id == PROJECT and dataset.requested_by_user_id == REVIEWER
    [submission] = dataset.submissions
    assert submission.message_id == 301
    assert submission.title == "Stress Test 0 - Sales Forecasting"
    assert submission.author_id == 7
    assert [a.filename for a in submission.attachments] == ["st0.pdf"]
    assert [l.url for l in submission.links] == ["https://kaggle.com/d/sales"]
    [comment] = submission.comments
    assert comment.comment_id == 401
    assert [a.filename for a in comment.attachments] == ["chart.png"]
    assert [l.url for l in comment.links] == ["https://github.com/s/repo"]
    assert "##Critique##" in comment.content_html  # raw body kept for STORY-001 detection


def test_messages_and_comments_across_pages_are_all_retrieved():
    messages_path = f"{P}/buckets/{PROJECT}/message_boards/{BOARD}/messages.json"
    second = {**MESSAGE, "id": 302}

    def paged(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[second])
        return httpx.Response(200, json=[MESSAGE], headers={
            "Link": f'<https://3.basecampapi.com{messages_path}?page=2>; rel="next"'})

    routes = {**full_project_routes(), messages_path: paged,
              f"{P}/buckets/{PROJECT}/recordings/302/comments.json": httpx.Response(200, json=[])}
    dataset = retrieve_project_submissions(client_for(fake_basecamp(routes)), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    assert [s.message_id for s in dataset.submissions] == [301, 302]
    assert [len(s.comments) for s in dataset.submissions] == [1, 0]


# --- AC2: a project with no submissions returns an empty dataset ---

def test_project_with_empty_message_board_returns_empty_dataset():
    routes = {**full_project_routes(),
              f"{P}/buckets/{PROJECT}/message_boards/{BOARD}/messages.json": httpx.Response(200, json=[])}
    dataset = retrieve_project_submissions(client_for(fake_basecamp(routes)), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    assert dataset.submissions == []


@pytest.mark.parametrize("project", [project_with_board(enabled=False), {"id": PROJECT, "dock": []}])
def test_project_without_an_enabled_message_board_returns_empty_dataset(project):
    handler = fake_basecamp({f"{P}/projects/{PROJECT}.json": httpx.Response(200, json=project)})
    dataset = retrieve_project_submissions(client_for(handler), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    assert dataset.submissions == []
    assert handler.calls == [f"{P}/projects/{PROJECT}.json"]


# --- Trust: every retrieval is logged with timestamp and user id ---

def audit_lines(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "stress_test_review.submission_retrieval"]


def test_successful_retrieval_logs_start_and_completion_with_timestamp_and_user_id(caplog):
    caplog.set_level(logging.INFO)
    retrieve_project_submissions(client_for(fake_basecamp(full_project_routes())), PROJECT, REVIEWER, audit=InMemoryAuditTrail(), correlation_id="corr-1")
    lines = audit_lines(caplog)
    assert [l["event"] for l in lines] == ["submission_retrieval_started", "submission_retrieval_completed"]
    for line in lines:
        assert line["timestamp"] and line["requested_by_user_id"] == REVIEWER
        assert line["project_id"] == PROJECT and line["correlation_id"] == "corr-1"
    done = lines[1]
    assert (done["submission_count"], done["comment_count"], done["attachment_count"], done["link_count"]) == (1, 1, 2, 2)
    assert FAKE_TOKEN not in caplog.text


def test_empty_project_retrieval_is_also_logged(caplog):
    caplog.set_level(logging.INFO)
    handler = fake_basecamp({f"{P}/projects/{PROJECT}.json": httpx.Response(200, json={"id": PROJECT, "dock": []})})
    retrieve_project_submissions(client_for(handler), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    assert audit_lines(caplog)[-1]["submission_count"] == 0


def test_missing_user_id_is_rejected_before_any_call():
    handler = fake_basecamp(full_project_routes())
    for bad in ["", "   ", None]:
        with pytest.raises(ValueError, match="requested_by_user_id"):
            retrieve_project_submissions(client_for(handler), PROJECT, bad, audit=InMemoryAuditTrail())
    assert handler.calls == []


@pytest.mark.parametrize("bad", [0, -1, True, "100"])
def test_invalid_project_id_is_rejected(bad):
    with pytest.raises(ValueError, match="project_id"):
        retrieve_project_submissions(client_for(fake_basecamp({})), bad, REVIEWER, audit=InMemoryAuditTrail())


# --- Failure paths: logged with error class and user id, then raised; no partial data ---

@pytest.mark.parametrize("response, expected", [
    (httpx.Response(401), BasecampAuthError),
    (httpx.Response(429), BasecampRateLimited),
    (httpx.Response(503), BasecampUnavailable),
])
def test_failure_during_comment_fetch_is_logged_and_raised(caplog, response, expected):
    caplog.set_level(logging.INFO)
    routes = {**full_project_routes(), f"{P}/buckets/{PROJECT}/recordings/301/comments.json": response}
    with pytest.raises(expected):
        retrieve_project_submissions(client_for(fake_basecamp(routes)), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    failed = audit_lines(caplog)[-1]
    assert failed["event"] == "submission_retrieval_failed"
    assert failed["requested_by_user_id"] == REVIEWER and failed["outcome"] == "failure"
    assert failed["error_class"] == expected.error_class


def test_network_failure_is_logged_and_raised(caplog):
    caplog.set_level(logging.INFO)

    def down(request):
        raise httpx.ConnectError("down")

    with pytest.raises(BasecampUnavailable):
        retrieve_project_submissions(client_for(down), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    assert audit_lines(caplog)[-1]["error_class"] == "UpstreamUnavailable"


def test_malformed_message_is_a_contract_error_without_echoing_content():
    routes = {**full_project_routes(),
              f"{P}/buckets/{PROJECT}/message_boards/{BOARD}/messages.json":
                  httpx.Response(200, json=[{"subject": "secret student text", "id": "x"}])}
    with pytest.raises(BasecampResponseError) as exc:
        retrieve_project_submissions(client_for(fake_basecamp(routes)), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    assert "secret student text" not in str(exc.value)


def test_retrieving_twice_gives_the_same_submissions():
    first = retrieve_project_submissions(client_for(fake_basecamp(full_project_routes())), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    second = retrieve_project_submissions(client_for(fake_basecamp(full_project_routes())), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    assert first.submissions == second.submissions


def test_unexpected_error_still_closes_the_audit_trail(caplog):
    caplog.set_level(logging.INFO)

    def broken(request):
        raise httpx.DecodingError("garbled")  # an httpx error the client does not classify

    with pytest.raises(httpx.DecodingError):
        retrieve_project_submissions(client_for(broken), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    failed = audit_lines(caplog)[-1]
    assert failed["event"] == "submission_retrieval_failed"
    assert failed["error_class"] == "UnexpectedError" and failed["requested_by_user_id"] == REVIEWER


def test_comments_call_is_skipped_when_basecamp_says_there_are_none():
    routes = {**full_project_routes(),
              f"{P}/buckets/{PROJECT}/message_boards/{BOARD}/messages.json":
                  httpx.Response(200, json=[{**MESSAGE, "comments_count": 0}])}
    handler = fake_basecamp(routes)
    dataset = retrieve_project_submissions(client_for(handler), PROJECT, REVIEWER, audit=InMemoryAuditTrail())
    assert dataset.submissions[0].comments == []
    assert not any(path.endswith("/comments.json") for path in handler.calls)


# --- STORY-011: retrieval is recorded in the audit trail ---

class _FailingAuditTrail(InMemoryAuditTrail):
    """Records normally, except for the listed actions."""

    def __init__(self, failing_actions):
        super().__init__()
        self._failing = set(failing_actions)

    def record(self, event):
        if event.action in self._failing:
            raise AuditWriteError("disk full")
        super().record(event)


def test_a_successful_retrieval_is_recorded_as_started_then_completed():
    audit = InMemoryAuditTrail()
    retrieve_project_submissions(client_for(fake_basecamp(full_project_routes())), PROJECT, REVIEWER,
                                 audit=audit, correlation_id="corr-7")
    events = audit.read_all()
    assert [e.action for e in events] == ["retrieval_started", "retrieval_completed"]
    assert {(e.actor_id, e.project_id, e.correlation_id) for e in events} == {(REVIEWER, PROJECT, "corr-7")}


def test_a_failed_retrieval_is_recorded_with_its_error_class():
    audit = InMemoryAuditTrail()
    routes = {**full_project_routes(), f"{P}/buckets/{PROJECT}/recordings/301/comments.json": httpx.Response(401)}
    with pytest.raises(BasecampAuthError):
        retrieve_project_submissions(client_for(fake_basecamp(routes)), PROJECT, REVIEWER, audit=audit)
    started, failed = audit.read_all()
    assert (started.action, failed.action, failed.outcome) == ("retrieval_started", "retrieval_failed", "failure")
    assert failed.reason_code == BasecampAuthError.error_class


def test_if_the_start_cannot_be_recorded_basecamp_is_never_called():
    handler = fake_basecamp(full_project_routes())
    with pytest.raises(AuditWriteError):
        retrieve_project_submissions(client_for(handler), PROJECT, REVIEWER,
                                     audit=_FailingAuditTrail({"retrieval_started"}))
    assert handler.calls == []


def test_if_completion_cannot_be_recorded_no_data_is_returned():
    audit = _FailingAuditTrail({"retrieval_completed"})
    with pytest.raises(AuditWriteError):
        retrieve_project_submissions(client_for(fake_basecamp(full_project_routes())), PROJECT, REVIEWER, audit=audit)
    assert [e.action for e in audit.read_all()] == ["retrieval_started"]


def test_if_the_failure_cannot_be_recorded_the_basecamp_error_still_surfaces(caplog):
    caplog.set_level(logging.INFO)
    routes = {**full_project_routes(), f"{P}/buckets/{PROJECT}/recordings/301/comments.json": httpx.Response(503)}
    with pytest.raises(BasecampUnavailable):
        retrieve_project_submissions(client_for(fake_basecamp(routes)), PROJECT, REVIEWER,
                                     audit=_FailingAuditTrail({"retrieval_failed"}))
    assert any(line["event"] == "audit_write_failed" for line in audit_lines(caplog))


def test_an_oversized_user_id_is_rejected_before_any_call():
    handler = fake_basecamp(full_project_routes())
    with pytest.raises(ValueError):
        retrieve_project_submissions(client_for(handler), PROJECT, "u" * 129, audit=InMemoryAuditTrail())
    assert handler.calls == []
