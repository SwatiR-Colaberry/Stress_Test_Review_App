"""Who may call what (STORY-014, REQ-020).

require_signed_in  FastAPI dependency: the signed-in person, or 401
                   NOT_SIGNED_IN before the route runs, so nothing is read
                   or changed. main.py puts it on every router except
                   /auth and /health.
require_admin      As above, then 403 ADMIN_ONLY for a Reviewer (audited as
                   admin_action_refused).

Both answer 503 ROLE_LIST_UNAVAILABLE when the role list cannot be read:
never "signed in" by default. Pages are guarded separately by
app/auth/page_guard.py (a redirect to sign-in instead of a 401).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditTrail, AuditWriteError
from app.auth.dependencies import get_session_store
from app.auth.logs import log_event
from app.auth.roles import RoleStoreUnavailable
from app.auth.sessions import SESSION_COOKIE, Principal, SessionStore
from app.models import AuditEvent

# No max_length here: an oversized or garbage cookie must read as "not signed
# in" (401, so the page sends you to sign in), not as a 422. SessionStore
# ignores any token longer than MAX_TOKEN_LENGTH before hashing it.
TokenCookie = Cookie(default=None, alias=SESSION_COOKIE)
CorrelationHeader = Header(default=None, max_length=64)


def require_signed_in(request: Request, token: Optional[str] = TokenCookie,
                      sessions: SessionStore = Depends(get_session_store),
                      x_correlation_id: Optional[str] = CorrelationHeader) -> Principal:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    try:
        who = sessions.resolve(token)
    except RoleStoreUnavailable:
        log_event("request_refused", correlation_id, logging.ERROR, reason_code="ROLE_LIST_UNAVAILABLE",
                  error_class="RoleStoreUnavailable", path=request.url.path)
        raise HTTPException(503, {"reason_code": "ROLE_LIST_UNAVAILABLE",
                                  "message": "The reviewer list cannot be read right now. Try again later."}) from None
    if who is None:
        log_event("request_refused", correlation_id, logging.WARNING, reason_code="NOT_SIGNED_IN",
                  error_class="AuthError", path=request.url.path)
        raise HTTPException(401, {"reason_code": "NOT_SIGNED_IN",
                                  "message": "Not signed in, or your session has ended. Sign in with Basecamp."})
    return who


def require_admin(request: Request, who: Principal = Depends(require_signed_in),
                  audit: AuditTrail = Depends(get_audit_trail),
                  x_correlation_id: Optional[str] = CorrelationHeader) -> Principal:
    if who.is_admin:
        return who
    correlation_id = x_correlation_id or str(uuid.uuid4())
    try:
        audit.record(AuditEvent(event_id=str(uuid.uuid4()), recorded_at=datetime.now(timezone.utc),
                                action="admin_action_refused", actor_id=who.email, outcome="blocked",
                                correlation_id=correlation_id, role=who.role, reason_code="ADMIN_ONLY"))
    except AuditWriteError:  # still refused: refusing is the safe side
        log_event("admin_refusal_not_audited", correlation_id, logging.ERROR, error_class="AuditWriteError")
    log_event("request_refused", correlation_id, logging.WARNING, reason_code="ADMIN_ONLY",
              error_class="AuthError", path=request.url.path)
    raise HTTPException(403, {"reason_code": "ADMIN_ONLY", "message": "Only an admin can do this."})
