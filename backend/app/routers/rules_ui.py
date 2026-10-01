"""Rules page route (STORY-012): every active Stress Test rule module, for
reviewers. Read-only; every call is audited as rules_viewed (see
app/queue_ui/viewing.py). Reviewer identity: the signed-in Basecamp
user's email (STORY-014, app/auth/guards.py).

Status codes: 401 not signed in; 503 the rule registry or
the audit trail is unavailable (retrying is safe). A single unreadable module
is not an error: it is listed as unavailable with its reason code.
"""
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditTrail, AuditWriteError
from app.auth.guards import require_signed_in
from app.auth.sessions import Principal
from app.queue_ui import viewing
from app.rules.loader import MODULES_DIR
from app.rules_ui.models import RulesPage
from app.rules_ui.service import RulesReadError, rules_page

router = APIRouter(prefix="/rules-ui", tags=["rules page"])


def get_modules_dir() -> Path:
    return MODULES_DIR


@router.get("/modules", response_model=RulesPage)
def get_rules(modules_dir: Path = Depends(get_modules_dir), audit: AuditTrail = Depends(get_audit_trail),
              reviewer: Principal = Depends(require_signed_in),
              x_correlation_id: Optional[str] = Header(default=None, max_length=64)) -> RulesPage:
    try:
        return viewing.view_rules(reviewer.email, x_correlation_id or str(uuid.uuid4()), audit,
                                  lambda: rules_page(modules_dir))
    except viewing.ViewerRefused as exc:
        status = 401 if exc.reason_code == "MISSING_REVIEWER_IDENTITY" else 403
        raise HTTPException(status, {"reason_code": exc.reason_code, "message": str(exc)}) from exc
    except (RulesReadError, AuditWriteError) as exc:
        raise HTTPException(503, {
            "error_class": exc.error_class, "reason_code": getattr(exc, "reason_code", None),
            "message": "Could not load the rules: the rule registry or the audit trail is unavailable. Retry; it is safe.",
        }) from exc
