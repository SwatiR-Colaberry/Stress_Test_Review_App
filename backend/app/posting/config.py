"""Posting settings (STORY-006), read from environment variables.

BASECAMP_POSTING_ENABLED       "yes" to post to the real Basecamp. Default: off.
                               Stays off until STORY-014 (Basecamp sign-in)
                               ties every post to a verified reviewer
                               (user decision 2026-09-30).
BASECAMP_POSTING_PROJECT_IDS   Comma-separated Basecamp project ids feedback
                               may be posted into. Empty = none. A review
                               pointing anywhere else is refused, so a wrong
                               or tampered project id cannot post elsewhere.
BASECAMP_POSTING_TIME_LIMIT_S  Upper bound for one posting request, all
                               attempts included. Default 60, 5-300.

Real project ids belong in the git-ignored .env only (public repo).
Errors name the variable, never its value.
"""
import os
from typing import FrozenSet, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field


class PostingConfigError(Exception):
    error_class = "ConfigError"


class PostingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    allowed_project_ids: FrozenSet[int] = frozenset()
    time_limit_s: float = Field(default=60.0, ge=5, le=300)


def load_posting_config(environ: Optional[Mapping[str, str]] = None) -> PostingConfig:
    env = os.environ if environ is None else environ
    problems: List[str] = []

    enabled_raw = env.get("BASECAMP_POSTING_ENABLED", "").strip().lower()
    if enabled_raw not in ("", "yes", "no"):
        problems.append("BASECAMP_POSTING_ENABLED must be yes or no")

    project_ids = set()
    for part in env.get("BASECAMP_POSTING_PROJECT_IDS", "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or int(part) <= 0:
            problems.append("BASECAMP_POSTING_PROJECT_IDS must be positive whole numbers, comma-separated")
            break
        project_ids.add(int(part))

    time_limit = 60.0
    time_raw = env.get("BASECAMP_POSTING_TIME_LIMIT_S", "").strip()
    if time_raw:
        try:
            time_limit = float(time_raw)
        except ValueError:
            problems.append("BASECAMP_POSTING_TIME_LIMIT_S must be a number")
        else:
            if not 5 <= time_limit <= 300:
                problems.append("BASECAMP_POSTING_TIME_LIMIT_S must be between 5 and 300")

    if problems:
        raise PostingConfigError("; ".join(problems))
    return PostingConfig(enabled=enabled_raw == "yes", allowed_project_ids=frozenset(project_ids),
                         time_limit_s=time_limit)
