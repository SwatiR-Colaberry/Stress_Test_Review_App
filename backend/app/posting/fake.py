"""A fake Basecamp message thread for tests and the offline demo (STORY-006).
Nothing here talks to the real Basecamp.

post_failures / get_failures: what the next POST / GET does instead of
succeeding, in order: an exception to raise, an int status to answer, a
callable(request) -> response, or "land_then_timeout" (the comment is
created, then the answer is lost, as when a read times out).
"""
import json
from typing import Any, Iterable, List

import httpx

from app.basecamp.api_client import BasecampClient
from app.basecamp.config import BasecampConfig, load_basecamp_config

FAKE_BASECAMP = load_basecamp_config({
    "BASECAMP_ACCOUNT_ID": "999999", "BASECAMP_ACCESS_TOKEN": "fake-token-not-real",
    "BASECAMP_USER_AGENT": "Stress Test Review App (demo@example.com)",
})


class FakeThread:
    def __init__(self, post_failures: Iterable[Any] = (), get_failures: Iterable[Any] = ()) -> None:
        self.comments: List[dict] = []
        self.post_failures = list(post_failures)
        self.get_failures = list(get_failures)
        self.requests: List[str] = []
        self.paths: List[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.method)
        self.paths.append(request.url.path)
        failures = self.get_failures if request.method == "GET" else self.post_failures
        step = failures.pop(0) if failures else None
        if isinstance(step, Exception):
            raise step
        if isinstance(step, int):
            return httpx.Response(step)
        if callable(step):
            return step(request)
        if request.method == "GET":
            return httpx.Response(200, json=self.comments)
        created = {"id": 90000 + len(self.comments), "content": json.loads(request.content)["content"]}
        self.comments.append(created)
        if step == "land_then_timeout":
            raise httpx.ReadTimeout("no answer")
        return httpx.Response(201, json=created)

    def posts(self) -> int:
        return self.requests.count("POST")

    def client(self, config: BasecampConfig = FAKE_BASECAMP) -> BasecampClient:
        """A client whose own retries are off, so the posting service's retries are what you see."""
        return BasecampClient(config, transport=httpx.MockTransport(self.handler), max_attempts=1,
                              sleep=lambda s: None)
