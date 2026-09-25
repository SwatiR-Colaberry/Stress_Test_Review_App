"""A fake Basecamp API for demos (retrieve_submissions.py --demo). NOT live data.

Serves two projects shaped like real Basecamp 3/4 responses:
- DEMO_PROJECT_WITH_SUBMISSIONS: 2 messages; comments, attachments and links.
- DEMO_EMPTY_PROJECT: a message board with no messages.
Anything else returns 404. No network is used.
"""
from typing import Dict

import httpx

from app.basecamp.config import BasecampConfig

DEMO_ACCOUNT_ID = 999999
DEMO_PROJECT_WITH_SUBMISSIONS = 100
DEMO_EMPTY_PROJECT = 101
_BOARD = 200
_EMPTY_BOARD = 201


def demo_config() -> BasecampConfig:
    return BasecampConfig(account_id=DEMO_ACCOUNT_ID, access_token="demo",  # placeholder: the demo transport never checks it
                          user_agent="Stress Test Review App (demo)")


def demo_transport() -> httpx.MockTransport:
    root = f"/{DEMO_ACCOUNT_ID}"
    p, e = DEMO_PROJECT_WITH_SUBMISSIONS, DEMO_EMPTY_PROJECT
    routes: Dict[str, object] = {
        f"{root}/projects/{p}.json": {"id": p, "dock": [{"name": "message_board", "id": _BOARD, "enabled": True}]},
        f"{root}/projects/{e}.json": {"id": e, "dock": [{"name": "message_board", "id": _EMPTY_BOARD, "enabled": True}]},
        f"{root}/buckets/{e}/message_boards/{_EMPTY_BOARD}/messages.json": [],
        f"{root}/buckets/{p}/message_boards/{_BOARD}/messages.json": [
            {"id": 301, "subject": "Stress Test 0 - Demo Submission", "created_at": "2026-09-20T10:00:00Z",
             "creator": {"id": 7}, "comments_count": 1,
             "content": '<div>Problem statement and dataset: <a href="https://example.com/dataset">dataset</a>'
                        '<bc-attachment content-type="application/pdf" filename="st0-writeup.pdf" '
                        'url="https://example.com/st0-writeup.pdf"></bc-attachment></div>'},
            {"id": 302, "subject": "Stress Test 1 - Demo Submission", "created_at": "2026-09-22T10:00:00Z",
             "creator": {"id": 7}, "comments_count": 0, "content": "<div>No files in this one.</div>"},
        ],
        f"{root}/buckets/{p}/recordings/301/comments.json": [
            {"id": 401, "created_at": "2026-09-21T09:00:00Z", "creator": {"id": 7},
             "content": '<div>V2: <a href="https://example.com/repo">repo</a>'
                        '<bc-attachment content-type="image/png" filename="chart.png" '
                        'url="https://example.com/chart.png"></bc-attachment> ##Critique##</div>'},
        ],
        f"{root}/buckets/{p}/recordings/302/comments.json": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(request.url.path)
        return httpx.Response(404) if body is None else httpx.Response(200, json=body)

    return httpx.MockTransport(handler)
