"""A scripted stand-in for Claude (STORY-004): used by tests and the demo
script, never by a live evaluation. No network, no API key, no cost."""
from typing import List, Union

from app.evaluation.claude_client import ClaudeReply, EvaluationError, Evaluator
from app.evaluation.prompt import EvaluationPrompt
from app.models import ClaudeStageAnswer, TokenUsage

FAKE_USAGE = TokenUsage(input_tokens=400, cache_read_input_tokens=1500, output_tokens=100)


class ScriptedEvaluator(Evaluator):
    """Answers each evaluate() call with the next scripted answer, or raises
    the next scripted error. Records every prompt it was sent."""

    def __init__(self, *replies: Union[ClaudeStageAnswer, EvaluationError], input_tokens: int = 2000) -> None:
        self.replies = list(replies)
        self._size = input_tokens  # what count_tokens() reports
        self.prompts: List[EvaluationPrompt] = []

    @property
    def model(self) -> str:
        return "fake-claude"

    def count_tokens(self, prompt: EvaluationPrompt) -> int:
        return self._size

    def evaluate(self, prompt: EvaluationPrompt) -> ClaudeReply:
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("ScriptedEvaluator was called more times than scripted")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ClaudeReply(answer=reply, model=self.model, request_id=f"fake_{len(self.prompts)}", usage=FAKE_USAGE)
