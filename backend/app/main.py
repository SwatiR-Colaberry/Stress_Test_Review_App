"""FastAPI entry point (REQ-015: typed API via FastAPI + Pydantic).

Run with: uvicorn app.main:app --app-dir backend --reload
"""
from pathlib import Path

from fastapi import FastAPI
from app.logging_config import configure_logging
from app.web_static import RevalidatedStaticFiles as StaticFiles  # no stale shared CSS/JS (see module)

from app.routers import basecamp, human_review, posting, queue_ui, reviews, rules_ui, security

configure_logging()

app = FastAPI(title="Stress Test Review App", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(reviews.router)
app.include_router(security.router)
app.include_router(basecamp.router)
app.include_router(human_review.router)
app.include_router(posting.router)
app.include_router(queue_ui.router)
app.include_router(rules_ui.router)

# STORY-005 reviewer page (plain HTML/JS, no build step): /reviewer/?review=<id>
app.mount("/reviewer", StaticFiles(directory=Path(__file__).parent / "human_review" / "web", html=True), name="reviewer")

# STORY-012 Review Queue page (plain HTML/JS, no build step): /queue/
app.mount("/queue", StaticFiles(directory=Path(__file__).parent / "queue_ui" / "web", html=True), name="queue")

# STORY-012 Rules page (plain HTML/JS, no build step): /rules/ (#ST0-002 jumps to a rule)
app.mount("/rules", StaticFiles(directory=Path(__file__).parent / "rules_ui" / "web", html=True), name="rules")
