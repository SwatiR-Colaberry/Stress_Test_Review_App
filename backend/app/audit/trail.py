"""Audit trail (STORY-011): an append-only record of every action the system
takes on a submission.

Why not just the JSON log lines on stdout? Those are fire-and-forget: if a
line is lost, nothing notices. An audit write here either succeeds or raises
AuditWriteError, and callers must record the event BEFORE they report an
action as done, so no submission is processed without a record.

Storage: a JSON Lines file (one AuditEvent per line) under the git-ignored
data/audit/ folder. SQL Server is deliberately not used: existing tables and
procedures must not change (user rule, 2026-09-25), and the database access in
this app stays read-only. A database-backed trail can implement the same
AuditTrail interface later if one is approved.

Failure modes handled: the file or its folder cannot be written (disk full,
permissions, path is a directory) -> AuditWriteError, nothing is reported as
recorded; a torn last line from a crash mid-write -> the next event starts on
a new line, so only the torn line is lost; a corrupt line on read ->
AuditReadError naming the line, never skipped silently. Not handled: the file being edited or deleted by hand
(append-only is a convention of this code, not enforced by the OS).
"""
import json
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, List

from pydantic import ValidationError

from app.models import AuditEvent

# Anchored at the repo root (backend/app/audit/trail.py -> 3 levels up), not the
# working directory, so the server and scripts all write to the same file.
DEFAULT_AUDIT_TRAIL_PATH = Path(__file__).resolve().parents[3] / "data" / "audit" / "audit_trail.jsonl"


class AuditWriteError(Exception):
    """The event could not be durably recorded. The caller must not treat the
    action as done."""
    error_class = "AuditWriteError"


class AuditReadError(Exception):
    error_class = "AuditReadError"


class AuditTrail(ABC):
    @abstractmethod
    def record(self, event: AuditEvent) -> None:
        """Append one event. Returns only once it is stored; raises
        AuditWriteError otherwise."""

    @abstractmethod
    def read_all(self) -> List[AuditEvent]:
        """Every event, in the order it was recorded."""


class InMemoryAuditTrail(AuditTrail):
    """For tests and local runs where a file is not wanted."""

    def __init__(self) -> None:
        self._events: List[AuditEvent] = []
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def read_all(self) -> List[AuditEvent]:
        with self._lock:
            return list(self._events)


class JsonlFileAuditTrail(AuditTrail):
    def __init__(self, path: Path = DEFAULT_AUDIT_TRAIL_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        line = event.model_dump_json() + "\n"
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                # One write per line in append mode, then fsync: once record()
                # returns, the event survives a crash or restart.
                with open(self._path, "ab") as handle:
                    handle.write(self._separator(handle) + line.encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise AuditWriteError(
                    f"Could not record audit event {event.action} for event {event.event_id}: "
                    f"{type(exc).__name__}"
                ) from exc

    def _separator(self, handle: BinaryIO) -> bytes:
        """A crash mid-write can leave a last line with no newline. Without a
        separator the next event would be glued onto it and both would be
        lost; with one, only the torn line is unreadable (and read_all
        reports it by line number)."""
        if handle.tell() == 0:
            return b""
        with open(self._path, "rb") as reader:
            reader.seek(-1, os.SEEK_END)
            return b"" if reader.read(1) == b"\n" else b"\n"

    def read_all(self) -> List[AuditEvent]:
        with self._lock:
            if not self._path.exists():
                return []
            try:
                lines = self._path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                raise AuditReadError(f"Could not read the audit trail: {type(exc).__name__}") from exc
        events = []
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                events.append(AuditEvent.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise AuditReadError(f"Audit trail line {number} is not a valid event") from exc
        return events
