"""The process-wide audit trail, handed to routes via FastAPI Depends so tests
can override it (app.dependency_overrides) instead of writing to data/audit/.

AUDIT_TRAIL_PATH overrides the file location; unset, it is the git-ignored
data/audit/audit_trail.jsonl at the repo root.
"""
import os
from pathlib import Path

from app.audit.trail import DEFAULT_AUDIT_TRAIL_PATH, AuditTrail, JsonlFileAuditTrail

_trail = JsonlFileAuditTrail(Path(os.environ.get("AUDIT_TRAIL_PATH") or DEFAULT_AUDIT_TRAIL_PATH))


def get_audit_trail() -> AuditTrail:
    return _trail
