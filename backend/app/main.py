"""FastAPI entry point (REQ-015: typed API via FastAPI + Pydantic).

Run with: uvicorn app.main:app --app-dir backend --reload
"""
from fastapi import FastAPI

from app.routers import basecamp, reviews, security

app = FastAPI(title="Stress Test Review App", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(reviews.router)
app.include_router(security.router)
app.include_router(basecamp.router)
