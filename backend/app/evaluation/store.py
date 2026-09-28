"""Local stores for AI evaluations (STORY-004). SQL Server is not used: it
stays read-only (user rule, 2026-09-25).

Files, under the git-ignored data/evaluations/ (results quote student text):
  results.jsonl   one EvaluationResult per line
  usage.jsonl     one UsageRecord per Claude call
  locks/          one file per evaluation in progress

ResultStore (idempotency, rule 8): an evaluation is keyed on
(comment_id, rule_version). A stored result is returned instead of calling
Claude again; put() for a key that already has a result adds nothing.
claim() stops two runs from evaluating the same key at once: the lock file is
created with O_EXCL, so exactly one caller wins. A lock older than
STALE_LOCK_S (a crashed run) is taken over, so a crash cannot block a
submission forever. Only a successful result blocks a later call; after a
failure the key can be evaluated again.

UsageLedger (daily token limit, rule 10): every call's token usage is
appended; check_budget() refuses a call whose worst case (input tokens from
count_tokens + max_tokens) would take today's total (UTC) over the limit.
Known gap: a call that times out reports no usage, so the ledger can
undercount after timeouts.

Failure modes: a file that cannot be written -> EvaluationStoreError, and the
caller must not report the evaluation as stored; a torn last line from a crash
mid-write -> the next line starts fresh, only the torn line is lost; a corrupt
line on read -> EvaluationStoreError naming the file and line, never skipped.
Per-process thread locks guard each file; separate processes rely on O_APPEND
for whole-line appends (each line is one write), as the audit trail does.
"""
import os
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional, Type, TypeVar

from pydantic import BaseModel, Field, ValidationError

from app.models import EvaluationResult, TokenUsage

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "evaluations"
STALE_LOCK_S = 60 * 60  # above the worst-case run time at the maximum settings

M = TypeVar("M", bound=BaseModel)


class EvaluationStoreError(Exception):
    error_class = "EvaluationStoreError"


class EvaluationInProgressError(Exception):
    """Another run is evaluating the same (comment_id, rule_version) now."""
    error_class = "EvaluationInProgress"


class DailyTokenLimitExceededError(Exception):
    error_class = "DailyTokenLimitExceeded"


def append_line(path: Path, line: str) -> None:
    """Append one line durably. Raises EvaluationStoreError."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as handle:
            separator = b""
            if handle.tell() > 0:  # a torn last line must not swallow this one
                with open(path, "rb") as reader:
                    reader.seek(-1, os.SEEK_END)
                    separator = b"" if reader.read(1) == b"\n" else b"\n"
            handle.write(separator + line.encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise EvaluationStoreError(f"Could not write {path.name}: {type(exc).__name__}") from exc


def read_lines(path: Path, model: Type[M]) -> List[M]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvaluationStoreError(f"Could not read {path.name}: {type(exc).__name__}") from exc
    items = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            items.append(model.model_validate_json(line))
        except ValidationError as exc:
            raise EvaluationStoreError(f"{path.name} line {number} is not a valid record") from exc
    return items


class ResultStore:
    def __init__(self, directory: Path = DEFAULT_DIR, clock=time.time) -> None:
        self._path = Path(directory) / "results.jsonl"
        self._locks = Path(directory) / "locks"
        self._lock = threading.Lock()
        self._clock = clock

    def get(self, comment_id: int, rule_version: str) -> Optional[EvaluationResult]:
        with self._lock:
            for result in read_lines(self._path, EvaluationResult):
                if (result.comment_id, result.rule_version) == (comment_id, rule_version):
                    return result
        return None

    def put(self, result: EvaluationResult) -> EvaluationResult:
        """Store the result unless one exists for its key; return the stored one."""
        with self._lock:
            for existing in read_lines(self._path, EvaluationResult):
                if (existing.comment_id, existing.rule_version) == (result.comment_id, result.rule_version):
                    return existing
            append_line(self._path, result.model_dump_json())
            return result

    @contextmanager
    def claim(self, comment_id: int, rule_version: str) -> Iterator[None]:
        lock = self._locks / f"{comment_id}-{rule_version}.lock"
        self._acquire(lock)
        try:
            yield
        finally:
            try:
                lock.unlink()
            except FileNotFoundError:
                pass  # already gone (taken over as stale); nothing to release

    def _acquire(self, lock: Path) -> None:
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
            for _ in range(2):  # second pass only after removing a stale lock
                try:
                    handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    try:
                        age = self._clock() - lock.stat().st_mtime
                    except FileNotFoundError:
                        continue  # released between our two calls: try again
                    if age < STALE_LOCK_S:
                        raise EvaluationInProgressError(f"{lock.stem} is being evaluated by another run") from None
                    lock.unlink(missing_ok=True)
                    continue
                os.close(handle)
                return
        except OSError as exc:
            raise EvaluationStoreError(f"Could not claim {lock.stem}: {type(exc).__name__}") from exc
        raise EvaluationInProgressError(f"{lock.stem} is being evaluated by another run")


class UsageRecord(BaseModel):
    recorded_at: datetime
    comment_id: int
    stage: int = Field(ge=1)
    model: str
    request_id: Optional[str] = None
    usage: TokenUsage


class UsageLedger:
    def __init__(self, directory: Path = DEFAULT_DIR, daily_limit: int = 500_000) -> None:
        self._path = Path(directory) / "usage.jsonl"
        self._limit = daily_limit
        self._lock = threading.Lock()

    def record(self, record: UsageRecord) -> None:
        with self._lock:
            append_line(self._path, record.model_dump_json())

    def used_on(self, day: date) -> int:
        with self._lock:
            records = read_lines(self._path, UsageRecord)
        return sum(r.usage.total for r in records if r.recorded_at.astimezone(timezone.utc).date() == day)

    def check_budget(self, estimate: int, now: datetime) -> None:
        used = self.used_on(now.astimezone(timezone.utc).date())
        if used + estimate > self._limit:
            raise DailyTokenLimitExceededError(
                f"daily token limit {self._limit} would be exceeded: {used} used today, "
                f"this call may use up to {estimate}"
            )
