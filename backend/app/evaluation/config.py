"""Claude evaluation settings (STORY-004), read from environment variables.

The Anthropic API key is held as a SecretStr, so it never appears in repr(),
logs or error messages. Errors name the variable that is wrong, never its
value, and all problems are reported together in one EvaluationConfigError.
Scripts load the git-ignored .env first; app code reads os.environ only.

  variable                      default          allowed
  ANTHROPIC_API_KEY             (required)
  EVALUATION_MODEL              claude-sonnet-5
  EVALUATION_EFFORT             low              low | medium
  EVALUATION_TIMEOUT_S          60               10-300 (per attempt)
  EVALUATION_MAX_RETRIES        2                0-2
  EVALUATION_MAX_TOKENS         4000             500-16000 (output cap, incl. thinking)
  EVALUATION_MAX_INPUT_TOKENS   20000            1000-200000 (above: manual resolution)
  EVALUATION_DAILY_TOKEN_LIMIT  500000           >= 1000 (all tokens, UTC day)
"""
import os
from typing import Dict, List, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError


class EvaluationConfigError(Exception):
    """Configuration is missing or invalid. The message lists variable names only."""


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_key: SecretStr
    model: str = Field(default="claude-sonnet-5", min_length=1)
    effort: Literal["low", "medium"] = "low"
    timeout_s: float = Field(default=60.0, ge=10, le=300)
    max_retries: int = Field(default=2, ge=0, le=2)
    max_tokens: int = Field(default=4000, ge=500, le=16000)
    max_input_tokens: int = Field(default=20000, ge=1000, le=200000)
    daily_token_limit: int = Field(default=500000, ge=1000)


# variable -> (field, lowest, highest); highest None = no upper bound
_INTEGERS: Dict[str, Tuple[str, int, Optional[int]]] = {
    "EVALUATION_TIMEOUT_S": ("timeout_s", 10, 300),
    "EVALUATION_MAX_RETRIES": ("max_retries", 0, 2),
    "EVALUATION_MAX_TOKENS": ("max_tokens", 500, 16000),
    "EVALUATION_MAX_INPUT_TOKENS": ("max_input_tokens", 1000, 200000),
    "EVALUATION_DAILY_TOKEN_LIMIT": ("daily_token_limit", 1000, None),
}


def load_evaluation_config(environ: Optional[Mapping[str, str]] = None) -> EvaluationConfig:
    env = os.environ if environ is None else environ
    problems: List[str] = []
    values: Dict[str, object] = {}

    api_key = env.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        values["api_key"] = api_key
    else:
        problems.append("ANTHROPIC_API_KEY is missing or blank")

    model = env.get("EVALUATION_MODEL", "").strip()
    if model:
        values["model"] = model

    effort = env.get("EVALUATION_EFFORT", "").strip().lower()
    if effort:
        if effort in ("low", "medium"):
            values["effort"] = effort
        else:
            problems.append("EVALUATION_EFFORT must be low or medium")

    for var, (field, lowest, highest) in _INTEGERS.items():
        raw = env.get(var, "").strip()
        if not raw:
            continue
        if raw.isdigit() and int(raw) >= lowest and (highest is None or int(raw) <= highest):
            values[field] = int(raw)
        elif highest is None:
            problems.append(f"{var} must be a whole number of at least {lowest}")
        else:
            problems.append(f"{var} must be a whole number from {lowest} to {highest}")

    if problems:
        raise EvaluationConfigError("Evaluation configuration invalid: " + "; ".join(problems))
    try:
        return EvaluationConfig(**values)
    except ValidationError as exc:
        # Report field names only; pydantic's own message would echo input values.
        fields = sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})
        raise EvaluationConfigError("Evaluation configuration invalid: " + ", ".join(fields)) from None
