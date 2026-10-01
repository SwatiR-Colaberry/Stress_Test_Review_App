"""FastAPI entry point (REQ-015: typed API via FastAPI + Pydantic).

Run with: uvicorn app.main:app --app-dir backend --reload
"""
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from app.logging_config import configure_logging
from app.web_static import RevalidatedStaticFiles as StaticFiles  # no stale shared CSS/JS (see module)

from app.auth.config import AuthConfigError
from app.auth.guards import require_signed_in
from app.auth.page_guard import PageGuard
from app.auth.pages import refused_page
from app.routers import admin, auth, basecamp, human_review, posting, queue_ui, reviews, rules_ui, security

configure_logging()

app = FastAPI(title="Stress Test Review App", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.exception_handler(AuthConfigError)
def auth_config_error(request: Request, exc: AuthConfigError):
    """A malformed sign-in setting (STORY-014): refuse clearly, never crash.
    The message names the variable only, never its value."""
    message = "Sign-in is not configured correctly on this server. Ask the app's administrator."
    if request.url.path.startswith("/auth/") and request.url.path != "/auth/me":
        return HTMLResponse(refused_page(message), status_code=503)
    return JSONResponse({"detail": {"code": "AUTH_NOT_CONFIGURED", "message": message}}, status_code=503)


# STORY-014: only /health and /auth/* are open. Every other API needs a
# signed-in session (401 otherwise, before the route runs); admin-only routes
# add require_admin themselves. Pages are guarded by PageGuard (redirect).
app.include_router(auth.router)
_signed_in = [Depends(require_signed_in)]
for _router in (reviews.router, security.router, basecamp.router, human_review.router, posting.router,
                queue_ui.router, rules_ui.router, admin.router):
    app.include_router(_router, dependencies=_signed_in)
app.add_middleware(PageGuard)

# STORY-005 reviewer page (plain HTML/JS, no build step): /reviewer/?review=<id>
app.mount("/reviewer", StaticFiles(directory=Path(__file__).parent / "human_review" / "web", html=True), name="reviewer")

# STORY-012 Review Queue page (plain HTML/JS, no build step): /queue/
app.mount("/queue", StaticFiles(directory=Path(__file__).parent / "queue_ui" / "web", html=True), name="queue")

# STORY-012 Rules page (plain HTML/JS, no build step): /rules/ (#ST0-002 jumps to a rule)
app.mount("/rules", StaticFiles(directory=Path(__file__).parent / "rules_ui" / "web", html=True), name="rules")

# STORY-014 Admins page (plain HTML/JS, no build step): /admin/ (admins only; its API is /admin-ui)
app.mount("/admin", StaticFiles(directory=Path(__file__).parent / "auth" / "web", html=True), name="admin")
