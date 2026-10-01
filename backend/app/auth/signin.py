"""Signing in and out (STORY-014, REQ-020): the decisions, separate from HTTP.

complete_sign_in turns Basecamp's callback into either a session or a refusal
with a clear message. Checks, in order: sign-in configured; the person did not
deny access in Basecamp; the anti-forgery state matches the one this browser
was given; Basecamp confirms who they are; they belong to our Basecamp
account; they are on the reviewer or admin list.

Every sign-in, refusal and sign-out writes one audit event (who, when, reason
code). A sign-in is only completed once its audit event is stored; a refusal
or sign-out still happens if the audit write fails (refusing and signing out
are the safe side), and the failure is logged as an error.

Never logged or audited: the OAuth code, the Basecamp access token, the
session token. Emails go only into the git-ignored audit trail.
"""
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, SecretStr

from app.audit.trail import AuditTrail, AuditWriteError
from app.auth.basecamp_identity import IdentityError
from app.auth.config import AuthConfig
from app.auth.launchpad import LaunchpadClient
from app.auth.roles import Role, RoleStore, RoleStoreUnavailable
from app.auth.sessions import SessionStore
from app.basecamp.oauth import OAuthError
from app.auth.logs import log_event
from app.models import AuditAction, AuditEvent

UNIDENTIFIED = "unidentified"

# reason code -> (HTTP status, what the person is told)
REFUSALS = {
    "NOT_CONFIGURED": (503, "Sign-in is not set up on this server yet. Ask the app's administrator."),
    "BASECAMP_DENIED": (403, "Basecamp sign-in was cancelled, so you are not signed in."),
    "STATE_MISMATCH": (400, "This sign-in link has expired or was opened in a different browser. "
                            "Please sign in again."),
    "BASECAMP_ERROR": (502, "Basecamp could not confirm who you are right now. Please try again in a moment."),
    "NOT_IN_ACCOUNT": (403, "Your Basecamp login is not a member of the Basecamp account this app works "
                            "with, so access is refused."),
    "NOT_ON_LIST": (403, "You are signed in to Basecamp as {email}, but that address is not on the "
                         "reviewer or admin list, so access is refused. Ask an admin to add you."),
    "ROLE_LIST_UNAVAILABLE": (503, "The reviewer list cannot be read right now, so nobody can be let in. "
                                   "Please try again later or tell the app's administrator."),
    "AUDIT_UNAVAILABLE": (503, "Sign-in cannot be recorded right now, so it was not completed. "
                               "Please try again in a moment."),
}


class SignInResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_token: Optional[SecretStr] = None  # set only on success; goes into the cookie, nowhere else
    email: Optional[str] = None
    role: Optional[Role] = None
    reason_code: Optional[str] = None
    status_code: int = 200
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.session_token is not None


def new_state() -> str:
    return secrets.token_urlsafe(24)


def complete_sign_in(*, code: Optional[str], state: Optional[str], expected_state: Optional[str],
                     basecamp_error: Optional[str], config: AuthConfig, launchpad: LaunchpadClient,
                     roles: RoleStore, sessions: SessionStore, audit: AuditTrail,
                     correlation_id: str) -> SignInResult:
    def refuse(reason: str, email: Optional[str] = None) -> SignInResult:
        return _refuse(reason, email, audit, correlation_id)

    if config.missing_settings:
        return refuse("NOT_CONFIGURED")
    if basecamp_error or not code:
        return refuse("BASECAMP_DENIED")
    if not state or not expected_state or not secrets.compare_digest(state.encode(), expected_state.encode()):
        return refuse("STATE_MISMATCH")
    try:
        identity = launchpad.identify(code)
    except (OAuthError, IdentityError) as exc:
        log_event("basecamp_identity_failed", correlation_id, logging.WARNING, error_class=type(exc).__name__)
        return refuse("BASECAMP_ERROR")
    if config.account_id not in identity.account_ids:
        return refuse("NOT_IN_ACCOUNT", identity.email)
    try:
        role = roles.role_for(identity.email)
    except RoleStoreUnavailable:
        return refuse("ROLE_LIST_UNAVAILABLE", identity.email)
    if role is None:
        return refuse("NOT_ON_LIST", identity.email)
    try:
        audit.record(_event("signed_in", identity.email, correlation_id, role=role))
    except AuditWriteError:
        log_event("sign_in_not_audited", correlation_id, logging.ERROR, error_class="AuditWriteError")
        return SignInResult(reason_code="AUDIT_UNAVAILABLE", status_code=503,
                            message=REFUSALS["AUDIT_UNAVAILABLE"][1])
    token, _ = sessions.start(identity.email, identity.name)
    log_event("signed_in", correlation_id, role=role)
    return SignInResult(session_token=SecretStr(token), email=identity.email, role=role)


def sign_out(token: Optional[str], sessions: SessionStore, audit: AuditTrail, correlation_id: str) -> bool:
    """Ends the session (always) and records it. False when there was none."""
    ended = sessions.end(token)
    if ended is None:
        return False
    try:
        audit.record(_event("signed_out", ended.email, correlation_id))
    except AuditWriteError:
        log_event("sign_out_not_audited", correlation_id, logging.ERROR, error_class="AuditWriteError")
    log_event("signed_out", correlation_id)
    return True


def _refuse(reason: str, email: Optional[str], audit: AuditTrail, correlation_id: str) -> SignInResult:
    status, message = REFUSALS[reason]
    try:
        audit.record(_event("sign_in_refused", email or UNIDENTIFIED, correlation_id, reason_code=reason))
    except AuditWriteError:
        log_event("sign_in_refusal_not_audited", correlation_id, logging.ERROR, error_class="AuditWriteError",
             reason_code=reason)
    log_event("sign_in_refused", correlation_id, logging.WARNING, reason_code=reason)
    return SignInResult(email=email, reason_code=reason, status_code=status,
                        message=message.format(email=email or "an unknown address"))


def _event(action: AuditAction, actor: str, correlation_id: str, role: Optional[Role] = None,
           reason_code: Optional[str] = None) -> AuditEvent:
    return AuditEvent(event_id=str(uuid.uuid4()), recorded_at=datetime.now(timezone.utc), action=action,
                      actor_id=actor, outcome="blocked" if action == "sign_in_refused" else "success",
                      correlation_id=correlation_id, role=role, reason_code=reason_code)

