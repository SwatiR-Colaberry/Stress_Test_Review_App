"""FastAPI entry point (REQ-015: typed API via FastAPI + Pydantic).

Run with: uvicorn app.main:app --app-dir backend --reload
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.logging_config import configure_logging

from app.routers import basecamp, human_review, reviews, security

configure_logging()

app = FastAPI(title="Stress Test Review App", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(reviews.router)
app.include_router(security.router)
app.include_router(basecamp.router)
app.include_router(human_review.router)

# STORY-005 reviewer page (plain HTML/JS, no build step): /reviewer/?review=<id>
app.mount("/reviewer", StaticFiles(directory=Path(__file__).parent / "human_review" / "web", html=True), name="reviewer")
