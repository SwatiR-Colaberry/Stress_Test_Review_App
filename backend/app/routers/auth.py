"""Sign in with Basecamp (STORY-014, REQ-020).

GET  /auth/signin    "Sign in with Basecamp" page (also shown after sign-out)
GET  /auth/login     sends the browser to Basecamp, with a fresh anti-forgery
                     state in a 10-minute HttpOnly cookie
GET  /auth/callback  Basecamp returns here: session cookie + redirect on
                     success, an "Access refused" page with a clear reason
                     otherwise (see app/auth/signin.py)
GET  /auth/me        the signed-in person and role, or 401
POST /auth/logout    ends the session, then back to the sign-in page

Cookies: the session token is HttpOnly, SameSite=Lax (so another site cannot
post to /auth/logout or any API with it) and Secure unless AUTH_COOKIE_SECURE
is "no" (plain-http localhost only). Its max-age matches the 8-hour session.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Header, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.audit.dependencies import get_audit_trail
from app.audit.trail import AuditTrail
from app.auth import pages, signin
from app.auth.config import AuthConfig
from app.auth.dependencies import get_auth_config, get_launchpad_client, get_role_store, get_session_store
from app.auth.launchpad import LaunchpadClient
from app.auth.roles import Role, RoleStore
from app.auth.guards import TokenCookie, require_signed_in
from app.auth.sessions import SESSION_COOKIE, SESSION_LIFETIME, Principal, SessionStore

STATE_COOKIE = "str_signin_state"
NEXT_COOKIE = "str_signin_next"
STATE_MAX_AGE_S = 600

router = APIRouter(prefix="/auth", tags=["sign in"])

CorrelationHeader = Header(default=None, max_length=64)


class SignedInUser(BaseModel):
    email: str
    name: str
    role: Role
    expires_at: datetime


@router.get("/signin", response_class=HTMLResponse)
def signin_page(next: Optional[str] = Query(default=None, max_length=pages.MAX_NEXT_LENGTH),
                signed_out: bool = False, expired: bool = False) -> HTMLResponse:
    notice = ("You have signed out." if signed_out else
              "Your session has ended. Please sign in again." if expired else None)
    return HTMLResponse(pages.sign_in_page(next or pages.DEFAULT_NEXT, notice))


@router.get("/login")
def login(next: Optional[str] = Query(default=None, max_length=pages.MAX_NEXT_LENGTH),
          config: AuthConfig = Depends(get_auth_config),
          launchpad: LaunchpadClient = Depends(get_launchpad_client)):
    if config.missing_settings:
        return HTMLResponse(pages.refused_page(signin.REFUSALS["NOT_CONFIGURED"][1]), status_code=503)
    state = signin.new_state()
    response = RedirectResponse(launchpad.authorize_url(state), status_code=303)
    for name, value in ((STATE_COOKIE, state), (NEXT_COOKIE, pages.safe_next(next))):
        response.set_cookie(name, value, max_age=STATE_MAX_AGE_S, path="/auth", httponly=True,
                            samesite="lax", secure=config.cookie_secure)
    return response


@router.get("/callback")
def callback(code: Optional[str] = Query(default=None, max_length=512),
             state: Optional[str] = Query(default=None, max_length=128),
             error: Optional[str] = Query(default=None, max_length=128),
             # Cookies unbounded here on purpose: a garbage one is refused by the
             # state check / safe_next below with a clear page, not a 422.
             expected_state: Optional[str] = Cookie(default=None, alias=STATE_COOKIE),
             next_path: Optional[str] = Cookie(default=None, alias=NEXT_COOKIE),
             config: AuthConfig = Depends(get_auth_config),
             launchpad: LaunchpadClient = Depends(get_launchpad_client),
             roles: RoleStore = Depends(get_role_store), sessions: SessionStore = Depends(get_session_store),
             audit: AuditTrail = Depends(get_audit_trail),
             x_correlation_id: Optional[str] = CorrelationHeader):
    result = signin.complete_sign_in(code=code, state=state, expected_state=expected_state, basecamp_error=error,
                                     config=config, launchpad=launchpad, roles=roles, sessions=sessions,
                                     audit=audit, correlation_id=x_correlation_id or str(uuid.uuid4()))
    if result.ok:
        response = RedirectResponse(pages.safe_next(next_path), status_code=303)
        response.set_cookie(SESSION_COOKIE, result.session_token.get_secret_value(),
                            max_age=int(SESSION_LIFETIME.total_seconds()), path="/", httponly=True,
                            samesite="lax", secure=config.cookie_secure)
    else:
        response = HTMLResponse(pages.refused_page(result.message), status_code=result.status_code)
    for name in (STATE_COOKIE, NEXT_COOKIE):  # one use only
        response.delete_cookie(name, path="/auth")
    return response


@router.get("/me", response_model=SignedInUser)
def me(who: Principal = Depends(require_signed_in)) -> SignedInUser:
    return SignedInUser(email=who.email, name=who.name, role=who.role, expires_at=who.expires_at)


@router.post("/logout")
def logout(token: Optional[str] = TokenCookie, config: AuthConfig = Depends(get_auth_config),
           sessions: SessionStore = Depends(get_session_store), audit: AuditTrail = Depends(get_audit_trail),
           x_correlation_id: Optional[str] = CorrelationHeader) -> RedirectResponse:
    signin.sign_out(token, sessions, audit, x_correlation_id or str(uuid.uuid4()))
    response = RedirectResponse("/auth/signin?signed_out=1", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=config.cookie_secure)
    return response
