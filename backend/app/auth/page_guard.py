"""Sign-in check for the reviewer web pages (STORY-014, REQ-020).

The pages are static files (StaticFiles mounts), which FastAPI dependencies
cannot guard, so this middleware does it: a request for a protected page
without a live session gets a 303 to /auth/signin?next=<that page>, before any
HTML, script or style is served. The APIs those pages call are guarded by
app/auth/guards.py (401 instead of a redirect).

A role list that cannot be read, or malformed sign-in settings, answer 503
with the "Access refused" page: never let through by default. (This
middleware runs outside FastAPI's exception handlers, so it must catch
AuthConfigError itself; otherwise the page would be a bare 500.)
"""
import logging
import uuid
from urllib.parse import urlencode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.auth.config import AuthConfigError
from app.auth.dependencies import get_session_store
from app.auth.logs import log_event
from app.auth.pages import refused_page
from app.auth.roles import RoleStoreUnavailable
from app.auth.sessions import MAX_TOKEN_LENGTH, SESSION_COOKIE

PROTECTED_PAGES = ("/queue", "/reviewer", "/rules", "/admin")


def is_protected_page(path: str) -> bool:
    """/queue and /queue/... are pages; /queue-ui/... is an API (guarded elsewhere)."""
    return any(path == prefix or path.startswith(prefix + "/") for prefix in PROTECTED_PAGES)


class PageGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if not is_protected_page(request.url.path):
            return await call_next(request)
        # Honour test overrides of the session store, as route dependencies do.
        provider = request.app.dependency_overrides.get(get_session_store, get_session_store)
        token = request.cookies.get(SESSION_COOKIE)
        correlation_id = str(uuid.uuid4())
        try:
            who = provider().resolve(token if token and len(token) <= MAX_TOKEN_LENGTH else None)
        except AuthConfigError:  # already logged by get_auth_config, naming the variable
            return HTMLResponse(refused_page("Sign-in is not configured correctly on this server. "
                                             "Ask the app's administrator."), status_code=503)
        except RoleStoreUnavailable:
            log_event("page_refused", correlation_id, logging.ERROR, reason_code="ROLE_LIST_UNAVAILABLE",
                      error_class="RoleStoreUnavailable", path=request.url.path)
            return HTMLResponse(refused_page("The reviewer list cannot be read right now. Try again later."),
                                status_code=503)
        if who is None:
            log_event("page_refused", correlation_id, logging.WARNING, reason_code="NOT_SIGNED_IN",
                      path=request.url.path)
            target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse("/auth/signin?" + urlencode({"next": target}), status_code=303)
        return await call_next(request)
