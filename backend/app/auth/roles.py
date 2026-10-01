"""Who may use the app, and as what (STORY-014, REQ-020).

Two roles: a Reviewer works the Review Queue; an Admin can also add, remove and
change the role of reviewers and admins. Anyone on neither list is refused.

Storage: data/auth/roles.json (git-ignored: it holds staff emails), in the
app's own storage, never SQL Server (read-only rule). Bootstrap admins come
from AUTH_BOOTSTRAP_ADMIN_EMAILS (see config.py) and are never in the file.

Correctness guarantees:
- Every change, and every refused change, writes one audit event naming who,
  whose role and when. The file is written first; if the audit write then
  fails, the file is put back and AuditWriteError is raised, so no change
  stands without a record.
- Setting the role someone already has changes nothing and records nothing,
  so a retried request cannot produce a second event.
- The last admin cannot be removed or demoted; bootstrap admins cannot be
  touched from the app at all.

Failure modes handled: missing file -> nobody beyond the bootstrap admins;
unreadable or corrupt file -> RoleStoreUnavailable (fail closed: never read as
an empty list, which would hide a damaged file); write failure ->
RoleStoreUnavailable, the old file unchanged (temp file + atomic rename).
Not handled: several server processes writing at once (one in-process lock).
"""
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.audit.trail import AuditTrail, AuditWriteError
from app.auth.config import MAX_EMAIL_LENGTH, normalize_email
from app.auth.logs import log_event
from app.models import AuditAction, AuditEvent

DEFAULT_ROLES_PATH = Path(__file__).resolve().parents[3] / "data" / "auth" / "roles.json"

Role = Literal["reviewer", "admin"]


class RoleStoreUnavailable(Exception):
    error_class = "RoleStoreUnavailable"


class RoleChangeRefused(Exception):
    error_class = "RoleChangeRefused"

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class RoleEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    email: str = Field(min_length=3, max_length=MAX_EMAIL_LENGTH)
    role: Role
    updated_by: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)
    updated_at: datetime


class RoleAssignment(BaseModel):
    """One row of the role list as an admin sees it."""
    model_config = ConfigDict(frozen=True)

    email: str
    role: Role
    bootstrap: bool  # from AUTH_BOOTSTRAP_ADMIN_EMAILS: cannot be changed in the app


class _RolesFile(BaseModel):
    version: Literal[1] = 1
    entries: List[RoleEntry] = []


class RoleStore:
    def __init__(self, path: Path, bootstrap_admins: FrozenSet[str], audit: AuditTrail) -> None:
        self._path = Path(path)
        self._bootstrap = frozenset(bootstrap_admins)
        self._audit = audit
        self._lock = threading.Lock()

    def role_for(self, email: str) -> Optional[Role]:
        """The person's role, or None if they are on neither list. Bootstrap
        admins are answered without reading the file, so they can still sign in
        when it is damaged; anyone else then gets RoleStoreUnavailable."""
        email = normalize_email(email)
        if email in self._bootstrap:
            return "admin"
        entry = self._read().get(email)
        return entry.role if entry else None

    def list_assignments(self) -> List[RoleAssignment]:
        rows = [RoleAssignment(email=e, role="admin", bootstrap=True) for e in sorted(self._bootstrap)]
        rows += [RoleAssignment(email=e.email, role=e.role, bootstrap=False)
                 for e in sorted(self._read().values(), key=lambda e: e.email)]
        return rows

    def set_role(self, email: str, role: Role, by: str, correlation_id: str) -> Literal["added", "changed", "unchanged"]:
        """Adds the person or changes their role. Raises RoleChangeRefused
        (audited as blocked) for a bootstrap admin or the last admin."""
        email, by = normalize_email(email), normalize_email(by)
        with self._lock:
            entries = self._read()
            current = entries.get(email)
            action: AuditAction = "role_added" if current is None else "role_changed"
            if email in self._bootstrap:
                self._refuse(action, by, email, role, correlation_id, "BOOTSTRAP_ADMIN",
                             "this admin is set in the server configuration and cannot be changed here")
            if current is not None and current.role == role:
                return "unchanged"
            if current is not None and current.role == "admin" and self._admin_count(entries) == 1:
                self._refuse(action, by, email, role, correlation_id, "LAST_ADMIN",
                             "the last admin cannot be made a reviewer")
            entries[email] = RoleEntry(email=email, role=role, updated_by=by, updated_at=_now())
            self._commit(entries, self._event(action, by, email, role, correlation_id))
            return "added" if action == "role_added" else "changed"

    def remove(self, email: str, by: str, correlation_id: str) -> Literal["removed", "not_found"]:
        """Removes the person from both lists. Removing someone already gone
        changes nothing and records nothing."""
        email, by = normalize_email(email), normalize_email(by)
        with self._lock:
            entries = self._read()
            if email in self._bootstrap:
                self._refuse("role_removed", by, email, "admin", correlation_id, "BOOTSTRAP_ADMIN",
                             "this admin is set in the server configuration and cannot be removed here")
            current = entries.pop(email, None)
            if current is None:
                return "not_found"
            if current.role == "admin" and self._admin_count(entries) == 0:
                self._refuse("role_removed", by, email, "admin", correlation_id, "LAST_ADMIN",
                             "the last admin cannot be removed")
            self._commit(entries, self._event("role_removed", by, email, current.role, correlation_id))
            return "removed"

    # --- internals -----------------------------------------------------------

    def _admin_count(self, entries: Dict[str, RoleEntry]) -> int:
        return len(self._bootstrap) + sum(1 for e in entries.values() if e.role == "admin")

    def _refuse(self, action: AuditAction, by: str, email: str, role: Role, correlation_id: str,
                reason_code: str, message: str) -> None:
        self._audit.record(self._event(action, by, email, role, correlation_id, outcome="blocked",
                                       reason_code=reason_code))
        log_event("role_change_refused", correlation_id, logging.WARNING, reason_code=reason_code)
        raise RoleChangeRefused(reason_code, message)

    @staticmethod
    def _event(action: AuditAction, by: str, email: str, role: Role, correlation_id: str,
               outcome: str = "success", reason_code: Optional[str] = None) -> AuditEvent:
        return AuditEvent(event_id=str(uuid.uuid4()), recorded_at=_now(), action=action, actor_id=by,
                          outcome=outcome, correlation_id=correlation_id, subject_id=email, role=role,
                          reason_code=reason_code)

    def _commit(self, entries: Dict[str, RoleEntry], event: AuditEvent) -> None:
        previous = self._path.read_bytes() if self._path.exists() else None
        self._write(entries)
        try:
            self._audit.record(event)
        except AuditWriteError:
            self._restore(previous)
            log_event("role_change_not_audited", event.correlation_id, logging.ERROR, error_class="AuditWriteError")
            raise
        log_event(event.action, event.correlation_id, role=event.role)

    def _read(self) -> Dict[str, RoleEntry]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise self._unavailable("read", exc) from None
        try:
            parsed = _RolesFile.model_validate_json(raw)
        except ValidationError as exc:
            raise self._unavailable("parse", exc) from None
        return {e.email: e for e in parsed.entries}

    def _write(self, entries: Dict[str, RoleEntry]) -> None:
        body = _RolesFile(entries=sorted(entries.values(), key=lambda e: e.email)).model_dump_json(indent=2)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".roles-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self._path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise self._unavailable("write", exc) from None

    def _restore(self, previous: Optional[bytes]) -> None:
        try:
            if previous is None:
                self._path.unlink(missing_ok=True)
            else:
                self._path.write_bytes(previous)
        except OSError as exc:
            log_event("role_store_restore_failed", "role-store", logging.ERROR, error_class=type(exc).__name__)

    @staticmethod
    def _unavailable(step: str, exc: Exception) -> RoleStoreUnavailable:
        log_event("role_store_unavailable", "role-store", logging.ERROR, step=step, error_class=type(exc).__name__)
        return RoleStoreUnavailable(f"the reviewer/admin list is unavailable ({step} failed: {type(exc).__name__})")


def _now() -> datetime:
    return datetime.now(timezone.utc)

