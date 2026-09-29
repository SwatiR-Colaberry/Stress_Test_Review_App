"""Historical retrieval settings (STORY-013), read from environment variables.

  variable                   default               allowed
  HISTORY_TOP_K              10                    1-15 (MAX_HISTORY_CASES)
  HISTORY_INDEX_DIR          data/vector_index/    any folder (git-ignored by default)

A bad value raises HistoryConfigError naming the variable, at startup, not
in the middle of a review.
"""
import os
from pathlib import Path
from typing import Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.history.lancedb_index import DEFAULT_DIR
from app.models import MAX_HISTORY_CASES

DEFAULT_TOP_K = 10


class HistoryConfigError(Exception):
    pass


class HistoryConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_HISTORY_CASES)
    index_dir: Path = DEFAULT_DIR


def load_history_config(environ: Optional[Mapping[str, str]] = None) -> HistoryConfig:
    env = os.environ if environ is None else environ
    values = {}
    raw_k = env.get("HISTORY_TOP_K", "").strip()
    if raw_k:
        if not raw_k.isdigit() or not 1 <= int(raw_k) <= MAX_HISTORY_CASES:
            raise HistoryConfigError(f"HISTORY_TOP_K must be a whole number from 1 to {MAX_HISTORY_CASES}")
        values["top_k"] = int(raw_k)
    raw_dir = env.get("HISTORY_INDEX_DIR", "").strip()
    if raw_dir:
        values["index_dir"] = Path(raw_dir)
    return HistoryConfig(**values)
