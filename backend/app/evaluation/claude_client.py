"""Claude client for draft evaluations (STORY-004: REQ-005).

Evaluator is the seam: the orchestrator depends on it, tests and the demo
use a fake, and AnthropicEvaluator is the real one (official anthropic SDK).

One request per stage:
- system prompt in a block marked cache_control (identical across stages and
  submissions, so later calls read it from the prompt cache);
- structured output through output_config.format, built from
  ClaudeStageAnswer; effort from config; adaptive thinking; capped max_tokens.

Failure handling (every failure is one typed error with a stable error_class):
  error                    error_class          when
  EvaluationTimeoutError   TimeoutError         an attempt exceeded the timeout, retries used up
  ClaudeUnavailableError   UpstreamUnavailable  connection error, 429 or 5xx, retries used up
  ClaudeAuthError          AuthError            401 / 403 (never retried)
  MalformedReplyError      ContractViolation    400/404/413/422, reply cut off at max_tokens,
                                                or a reply that does not fit ClaudeStageAnswer
  EvaluationRefusedError   EvaluationRefused    stop_reason "refusal"
Retries: the SDK's own retries are switched off (max_retries=0) because it
honours any Retry-After, however long. Here: at most config.max_retries (<= 2)
retries, only for connection errors, timeouts, 429 and 5xx, waiting
Retry-After capped at MAX_RETRY_WAIT_S, else 1 s then 2 s. Worst case per
call: (retries + 1) x timeout + 2 x 30 s. Nothing is ever retried forever.

Logging: one JSON line per attempt (claude_call_completed / _failed) with
model, duration, request id, stop reason and token usage. Never the key,
never the prompt or the student's text.
"""
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Type, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.evaluation.config import EvaluationConfig
from app.evaluation.prompt import EvaluationPrompt
from app.models import ClaudeStageAnswer, TokenUsage

logger = logging.getLogger("stress_test_review.evaluation")

MAX_RETRY_WAIT_S = 30.0
_BACKOFF_S = (1.0, 2.0)
_RETRYABLE_STATUS = {408, 409, 429}


class EvaluationError(Exception):
    """usage / request_id are set when Claude did answer (refused, cut off or
    malformed): those tokens were spent and must reach the usage ledger."""
    error_class = "EvaluationError"

    def __init__(self, message: str, usage: Optional[TokenUsage] = None, request_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.usage = usage
        self.request_id = request_id


class EvaluationTimeoutError(EvaluationError):
    error_class = "TimeoutError"


class ClaudeUnavailableError(EvaluationError):
    error_class = "UpstreamUnavailable"


class ClaudeAuthError(EvaluationError):
    error_class = "AuthError"


class MalformedReplyError(EvaluationError):
    error_class = "ContractViolation"


class EvaluationRefusedError(EvaluationError):
    error_class = "EvaluationRefused"


class ClaudeReply(BaseModel):
    answer: ClaudeStageAnswer
    model: str  # the model that actually answered
    request_id: Optional[str] = None
    usage: TokenUsage


class Evaluator(ABC):
    @property
    @abstractmethod
    def model(self) -> str:
        """The configured model id."""

    @abstractmethod
    def count_tokens(self, prompt: EvaluationPrompt) -> int:
        """Input tokens this prompt would use. Raises EvaluationError."""

    @abstractmethod
    def evaluate(self, prompt: EvaluationPrompt) -> ClaudeReply:
        """Claude's answer for one stage. Raises EvaluationError."""


def output_schema() -> Dict[str, Any]:
    """The structured-output schema for ClaudeStageAnswer. The models'
    docstrings (developer notes) are dropped: they would cost tokens on every
    call. Field constraints stay, as hints the SDK moves into descriptions."""
    schema = ClaudeStageAnswer.model_json_schema()
    schema.pop("description", None)
    for definition in schema.get("$defs", {}).values():
        definition.pop("description", None)
    return anthropic.transform_schema(schema)


T = TypeVar("T")


class AnthropicEvaluator(Evaluator):
    def __init__(
        self,
        config: EvaluationConfig,
        client: Optional[anthropic.Anthropic] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._client = client or anthropic.Anthropic(
            api_key=config.api_key.get_secret_value(), timeout=config.timeout_s, max_retries=0
        )
        self._sleep = sleep
        self._schema = output_schema()

    @property
    def model(self) -> str:
        return self._config.model

    def _request(self, prompt: EvaluationPrompt) -> Dict[str, Any]:
        return {
            "model": self._config.model,
            "system": [{"type": "text", "text": prompt.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": prompt.user}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self._config.effort, "format": {"type": "json_schema", "schema": self._schema}},
        }

    def count_tokens(self, prompt: EvaluationPrompt) -> int:
        result = self._with_retries("count_tokens", lambda: self._client.messages.count_tokens(**self._request(prompt)))
        return result.input_tokens

    def evaluate(self, prompt: EvaluationPrompt) -> ClaudeReply:
        message = self._with_retries(
            "messages",
            lambda: self._client.messages.create(max_tokens=self._config.max_tokens, **self._request(prompt)),
        )
        usage = TokenUsage(
            input_tokens=message.usage.input_tokens or 0,
            cache_creation_input_tokens=message.usage.cache_creation_input_tokens or 0,
            cache_read_input_tokens=message.usage.cache_read_input_tokens or 0,
            output_tokens=message.usage.output_tokens or 0,
        )
        request_id = getattr(message, "_request_id", None)
        if message.stop_reason == "refusal":
            raise EvaluationRefusedError(f"Claude declined to evaluate (request {request_id})", usage, request_id)
        if message.stop_reason == "max_tokens":
            raise MalformedReplyError(
                f"reply cut off at max_tokens={self._config.max_tokens} (request {request_id})", usage, request_id
            )
        text = next((block.text for block in message.content if block.type == "text"), None)
        if text is None:
            raise MalformedReplyError(f"reply has no text block (request {request_id})", usage, request_id)
        try:
            answer = ClaudeStageAnswer.model_validate_json(text)
        except ValidationError as exc:
            fields = sorted({".".join(str(part) for part in err["loc"]) for err in exc.errors()})
            raise MalformedReplyError(
                f"reply does not fit the schema ({', '.join(fields) or 'invalid JSON'}; request {request_id})",
                usage, request_id,
            ) from None
        return ClaudeReply(answer=answer, model=message.model, request_id=request_id, usage=usage)

    def _with_retries(self, operation: str, call: Callable[[], T]) -> T:
        attempts = self._config.max_retries + 1
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                result = call()
            except anthropic.APIStatusError as exc:
                retryable = exc.status_code in _RETRYABLE_STATUS or exc.status_code >= 500
                self._log_failure(operation, attempt, started, type(exc).__name__, exc.status_code)
                if exc.status_code in (401, 403):
                    raise ClaudeAuthError(f"Anthropic rejected the API key ({exc.status_code})") from None
                if not retryable:
                    raise MalformedReplyError(f"Anthropic rejected the request ({exc.status_code})") from None
                if attempt == attempts:
                    raise ClaudeUnavailableError(
                        f"Claude API unavailable ({exc.status_code}) after {attempts} attempts"
                    ) from None
                self._sleep(self._wait(attempt, exc.response.headers.get("retry-after")))
                continue
            except anthropic.APITimeoutError:
                self._log_failure(operation, attempt, started, "APITimeoutError", None)
                if attempt == attempts:
                    raise EvaluationTimeoutError(
                        f"Claude did not answer within {self._config.timeout_s:.0f} s, {attempts} attempts"
                    ) from None
                self._sleep(self._wait(attempt, None))
                continue
            except anthropic.APIConnectionError:
                self._log_failure(operation, attempt, started, "APIConnectionError", None)
                if attempt == attempts:
                    raise ClaudeUnavailableError(f"Claude API unreachable after {attempts} attempts") from None
                self._sleep(self._wait(attempt, None))
                continue
            self._log_success(operation, attempt, started, result)
            return result
        raise AssertionError("unreachable")  # the loop always returns or raises

    @staticmethod
    def _wait(attempt: int, retry_after: Optional[str]) -> float:
        try:
            if retry_after is not None:
                return min(max(float(retry_after), 0.0), MAX_RETRY_WAIT_S)
        except ValueError:
            pass  # an HTTP-date or junk: fall back to the fixed backoff
        return _BACKOFF_S[min(attempt - 1, len(_BACKOFF_S) - 1)]

    def _log_success(self, operation: str, attempt: int, started: float, result: Any) -> None:
        usage = getattr(result, "usage", None)
        context: Dict[str, Any] = {"operation": operation, "model": self._config.model, "attempt": attempt}
        if usage is not None:
            context.update(
                stop_reason=getattr(result, "stop_reason", None),
                input_tokens=usage.input_tokens,
                cache_creation_input_tokens=usage.cache_creation_input_tokens,
                cache_read_input_tokens=usage.cache_read_input_tokens,
                output_tokens=usage.output_tokens,
            )
        else:
            context["input_tokens"] = getattr(result, "input_tokens", None)
        logger.info(json.dumps({
            "event": "claude_call_completed", "outcome": "success",
            "duration_ms": round((time.monotonic() - started) * 1000),
            "request_id": getattr(result, "_request_id", None), "context": context,
        }))

    def _log_failure(self, operation: str, attempt: int, started: float, error_class: str, status: Optional[int]) -> None:
        logger.warning(json.dumps({
            "event": "claude_call_failed", "outcome": "failure", "error_class": error_class,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "context": {"operation": operation, "model": self._config.model, "attempt": attempt, "status": status},
        }))
