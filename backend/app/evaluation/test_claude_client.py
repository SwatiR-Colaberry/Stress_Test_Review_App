"""AnthropicEvaluator against the real SDK with an in-memory HTTP transport:
no network, no API key, no cost."""
import json
import logging

import anthropic
import httpx2
import pytest

from app.evaluation.claude_client import (
    AnthropicEvaluator,
    ClaudeAuthError,
    ClaudeUnavailableError,
    EvaluationRefusedError,
    EvaluationTimeoutError,
    MalformedReplyError,
    output_schema,
)
from app.evaluation.config import EvaluationConfig
from app.evaluation.prompt import EvaluationPrompt

_KEY = "sk-ant-test-not-a-real-key-1111"
_PROMPT = EvaluationPrompt(system="SYSTEM PROMPT", user="Judge only these Stage 1 rules: ST0-001")
_ANSWER = {
    "passed_rule_ids": ["ST0-002"],
    "findings": [{
        "rule_id": "ST0-001", "status": "FAIL", "severity": "Required Fix",
        "evidence": "No dataset description.", "reason": "ST0-001 needs one.",
        "suggested_feedback": "Please add a brief description of the dataset.", "confidence": 0.8,
    }],
}


def _message(text=None, stop_reason="end_turn", model="claude-sonnet-5"):
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "text", "text": json.dumps(_ANSWER) if text is None else text}],
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 300, "output_tokens": 120,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 1500},
    }


class _Server:
    """Replays the given responses in order and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, body = response[0], response[1]
        headers = {"request-id": "req_test", **(response[2] if len(response) > 2 else {})}
        return httpx2.Response(status, json=body, headers=headers)


def _evaluator(server, **config):
    sleeps = []
    client = anthropic.Anthropic(
        api_key=_KEY, max_retries=0, base_url="https://api.test",
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(server)),
    )
    evaluator = AnthropicEvaluator(EvaluationConfig(api_key=_KEY, **config), client=client, sleep=sleeps.append)
    return evaluator, sleeps


def _error(status, error_type="api_error"):
    return (status, {"type": "error", "error": {"type": error_type, "message": "test"}})


def test_a_good_reply_is_parsed_with_usage_model_and_request_id():
    server = _Server((200, _message()))
    evaluator, _ = _evaluator(server)
    reply = evaluator.evaluate(_PROMPT)
    assert reply.answer.passed_rule_ids == ["ST0-002"]
    assert reply.answer.findings[0].rule_id == "ST0-001"
    assert (reply.model, reply.request_id) == ("claude-sonnet-5", "req_test")
    assert (reply.usage.input_tokens, reply.usage.cache_read_input_tokens, reply.usage.output_tokens) == (300, 1500, 120)


def test_the_request_carries_cache_marker_effort_schema_and_token_cap():
    server = _Server((200, _message()))
    evaluator, _ = _evaluator(server, effort="medium", max_tokens=3000)
    evaluator.evaluate(_PROMPT)
    body = json.loads(server.requests[0].content)
    assert body["model"] == "claude-sonnet-5"
    assert body["max_tokens"] == 3000
    assert body["system"] == [{"type": "text", "text": "SYSTEM PROMPT", "cache_control": {"type": "ephemeral"}}]
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": output_schema()}
    assert body["thinking"] == {"type": "adaptive"}
    assert body["messages"] == [{"role": "user", "content": _PROMPT.user}]


def test_the_output_schema_has_no_developer_docstrings():
    schema = json.dumps(output_schema())
    assert "STORY-005" not in schema and "structured-output schema" not in schema
    assert "maxLength: 300" in schema  # constraints survive as hints


def test_count_tokens_uses_the_same_request_shape():
    server = _Server((200, {"input_tokens": 2100}))
    evaluator, _ = _evaluator(server)
    assert evaluator.count_tokens(_PROMPT) == 2100
    assert server.requests[0].url.path == "/v1/messages/count_tokens"
    body = json.loads(server.requests[0].content)
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "max_tokens" not in body


def test_an_overload_that_recovers_is_retried():
    server = _Server(_error(529, "overloaded_error"), (200, _message()))
    evaluator, sleeps = _evaluator(server)
    assert evaluator.evaluate(_PROMPT).answer.passed_rule_ids == ["ST0-002"]
    assert sleeps == [1.0]


def test_repeated_server_errors_give_up_after_two_retries():
    server = _Server(_error(500), _error(500), _error(500), (200, _message()))
    evaluator, sleeps = _evaluator(server)
    with pytest.raises(ClaudeUnavailableError, match="after 3 attempts"):
        evaluator.evaluate(_PROMPT)
    assert len(server.requests) == 3
    assert sleeps == [1.0, 2.0]


def test_retry_after_is_honoured_but_capped():
    server = _Server((429, {"type": "error", "error": {"type": "rate_limit_error", "message": "x"}},
                      {"retry-after": "3600"}), (200, _message()))
    evaluator, sleeps = _evaluator(server)
    evaluator.evaluate(_PROMPT)
    assert sleeps == [30.0]


def test_an_unreachable_api_is_retried_then_reported():
    server = _Server(*[httpx2.ConnectError("refused")] * 3)
    evaluator, _ = _evaluator(server)
    with pytest.raises(ClaudeUnavailableError, match="unreachable"):
        evaluator.evaluate(_PROMPT)
    assert len(server.requests) == 3


def test_an_evaluation_over_the_time_limit_is_a_timeout_error():
    server = _Server(*[httpx2.ReadTimeout("slow")] * 3)
    evaluator, _ = _evaluator(server, timeout_s=10)
    with pytest.raises(EvaluationTimeoutError, match="within 10 s"):
        evaluator.evaluate(_PROMPT)
    assert len(server.requests) == 3


def test_retries_can_be_switched_off():
    server = _Server(httpx2.ReadTimeout("slow"))
    evaluator, _ = _evaluator(server, max_retries=0)
    with pytest.raises(EvaluationTimeoutError):
        evaluator.evaluate(_PROMPT)
    assert len(server.requests) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_key_is_not_retried(status):
    server = _Server(_error(status, "authentication_error"))
    evaluator, _ = _evaluator(server)
    with pytest.raises(ClaudeAuthError):
        evaluator.evaluate(_PROMPT)
    assert len(server.requests) == 1


def test_a_bad_request_is_not_retried():
    server = _Server(_error(400, "invalid_request_error"))
    evaluator, _ = _evaluator(server)
    with pytest.raises(MalformedReplyError, match="400"):
        evaluator.evaluate(_PROMPT)
    assert len(server.requests) == 1


def test_a_refusal_is_reported():
    server = _Server((200, _message(text="", stop_reason="refusal")))
    evaluator, _ = _evaluator(server)
    with pytest.raises(EvaluationRefusedError):
        evaluator.evaluate(_PROMPT)


def test_a_reply_cut_off_at_max_tokens_is_malformed_and_carries_its_usage():
    server = _Server((200, _message(text='{"passed_rule_ids": ["ST0-0', stop_reason="max_tokens")))
    evaluator, _ = _evaluator(server)
    with pytest.raises(MalformedReplyError, match="max_tokens") as caught:
        evaluator.evaluate(_PROMPT)
    assert caught.value.usage.output_tokens == 120  # spent tokens reach the ledger
    assert caught.value.request_id == "req_test"


def test_a_refusal_carries_its_usage():
    server = _Server((200, _message(text="", stop_reason="refusal")))
    evaluator, _ = _evaluator(server)
    with pytest.raises(EvaluationRefusedError) as caught:
        evaluator.evaluate(_PROMPT)
    assert caught.value.usage.input_tokens == 300


def test_a_timeout_has_no_usage():
    server = _Server(httpx2.ReadTimeout("slow"))
    evaluator, _ = _evaluator(server, max_retries=0)
    with pytest.raises(EvaluationTimeoutError) as caught:
        evaluator.evaluate(_PROMPT)
    assert caught.value.usage is None


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        json.dumps({"passed_rule_ids": [], "findings": [{**_ANSWER["findings"][0], "status": "PASS"}]}),
        json.dumps({"passed_rule_ids": [], "findings": [{**_ANSWER["findings"][0], "evidence": "x" * 301}]}),
        json.dumps({"passed_rule_ids": ["ST0-001"], "findings": _ANSWER["findings"]}),
        json.dumps({**_ANSWER, "approved": True}),
    ],
)
def test_a_reply_that_breaks_the_schema_is_malformed(text):
    server = _Server((200, _message(text=text)))
    evaluator, _ = _evaluator(server)
    with pytest.raises(MalformedReplyError):
        evaluator.evaluate(_PROMPT)


def test_the_key_and_prompt_never_reach_logs_or_errors(caplog):
    caplog.set_level(logging.DEBUG, logger="stress_test_review.evaluation")
    server = _Server((200, _message()), _error(500), _error(500), _error(500))
    evaluator, _ = _evaluator(server)
    evaluator.evaluate(_PROMPT)
    with pytest.raises(ClaudeUnavailableError) as caught:
        evaluator.evaluate(_PROMPT)
    logged = caplog.text + str(caught.value)
    assert _KEY not in logged
    assert "SYSTEM PROMPT" not in logged and "Judge only" not in logged
    assert '"cache_read_input_tokens": 1500' in caplog.text


def test_the_default_client_is_built_without_sdk_retries():
    evaluator = AnthropicEvaluator(EvaluationConfig(api_key=_KEY, timeout_s=45))
    assert evaluator._client.max_retries == 0
    assert evaluator._client.timeout == 45


def test_tests_have_no_real_claude_credentials():
    """backend/conftest.py removes every credential source for every test, so a
    client that is not given a key and a fake transport cannot reach the paid API."""
    import os

    assert "ANTHROPIC_API_KEY" not in os.environ
    with pytest.raises(anthropic.CredentialsError):  # raised before any request is sent
        anthropic.Anthropic(max_retries=0).messages.count_tokens(
            model="claude-sonnet-5", messages=[{"role": "user", "content": "x"}]
        )
