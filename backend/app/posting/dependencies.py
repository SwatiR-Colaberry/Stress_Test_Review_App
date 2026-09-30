"""Process-wide posting dependencies (STORY-006), handed to the route via
FastAPI Depends so tests can override them instead of writing to data/ or
calling Basecamp.

Settings are read on every request, so changing .env / the environment and
restarting is all it takes; a bad value answers 503 naming the variable.
REVIEWS_DIR overrides the folder of posted.jsonl (as for the reviewer store).
"""
import os
from pathlib import Path
from typing import Callable

from fastapi import HTTPException

from app.basecamp.api_client import BasecampClient
from app.basecamp.config import load_basecamp_config
from app.posting.config import PostingConfig, PostingConfigError, load_posting_config
from app.posting.store import DEFAULT_DIR, PostingStore

_store = PostingStore(Path(os.environ.get("REVIEWS_DIR") or DEFAULT_DIR))


def get_posting_store() -> PostingStore:
    return _store


def get_posting_config() -> PostingConfig:
    try:
        return load_posting_config()
    except PostingConfigError as exc:  # message names variables only
        raise HTTPException(503, {"error_class": exc.error_class, "message": str(exc)}) from exc


def get_basecamp_client_factory() -> Callable[[], BasecampClient]:
    """Builds the real client only when a post is actually attempted; missing
    Basecamp settings then raise BasecampConfigError inside the service."""
    return lambda: BasecampClient(load_basecamp_config())
