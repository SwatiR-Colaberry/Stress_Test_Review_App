"""Read-only HTTP client for the Basecamp 3/4 API (REQ-004, REQ-012).

Authenticates with the OAuth 2.0 bearer token from BasecampConfig. Every call
has an explicit timeout and a capped number of attempts.

Failure handling:
- 429 (rate limited): wait Retry-After seconds (capped at max_retry_after_s;
  backoff schedule if the header is missing or unreadable), then retry.
  Still 429 on the last attempt -> BasecampRateLimited.
- 5xx, network errors, timeouts: retry with the backoff schedule.
  Still failing on the last attempt -> BasecampUnavailable.
- 401/403 (invalid, expired or under-privileged token): BasecampAuthError at
  once. Never retried: the same token will fail again.
- Any other non-2xx, or a body that is not JSON: BasecampResponseError, not
  retried (a contract problem, not an outage).
Not handled here: refreshing an expired token (needs a registered Basecamp app;
see config.py). The caller surfaces the error; nothing is written on failure.

Pagination follows the Link rel="next" header, at most max_pages pages. A next
link pointing at any host other than the Basecamp API, or not using https, is
refused, so the token is never sent elsewhere or in clear text.
Redirects are not followed (a 3xx is an unexpected response), for the same reason.

Logs one JSON line per attempt with method, path (no query string), status,
duration and error class. Never the token, headers or response body.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Sequence
from urllib.parse import urlparse

import httpx

from app.basecamp.config import API_ROOT, BasecampConfig

logger = logging.getLogger("stress_test_review.basecamp_api")


class BasecampError(Exception):
    error_class = "BasecampError"

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BasecampAuthError(BasecampError):
    error_class = "AuthError"


class BasecampRateLimited(BasecampError):
    error_class = "RateLimitError"


class BasecampUnavailable(BasecampError):
    error_class = "UpstreamUnavailable"


class BasecampResponseError(BasecampError):
    error_class = "ContractViolation"


class BasecampClient:
    def __init__(
        self,
        config: BasecampConfig,
        transport: Optional[httpx.BaseTransport] = None,
        max_attempts: int = 3,
        backoff_s: Sequence[float] = (1.0, 2.0),
        max_retry_after_s: float = 30.0,
        max_pages: int = 50,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        if max_attempts < 1 or not backoff_s or max_pages < 1:
            raise ValueError("max_attempts and max_pages must be >= 1 and backoff_s non-empty")
        self._config = config
        self._max_attempts = max_attempts
        self._backoff_s = tuple(backoff_s)
        self._max_retry_after_s = max_retry_after_s
        self._max_pages = max_pages
        self._sleep = sleep or time.sleep
        self._http = httpx.Client(
            headers=config.auth_headers(),
            timeout=config.timeout_s,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "BasecampClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_json(self, path: str) -> Any:
        """GET one resource, e.g. "/projects/123.json". Returns the parsed JSON."""
        return _parse_json(self._request(self._url(path)))

    def get_all(self, path: str) -> List[Any]:
        """GET a paginated list, following Link rel="next". Returns all items."""
        items: List[Any] = []
        url: Optional[str] = self._url(path)
        for _ in range(self._max_pages):
            if url is None:
                return items
            response = self._request(url)
            page = _parse_json(response)
            if not isinstance(page, list):
                raise BasecampResponseError("Expected a JSON list", response.status_code)
            items.extend(page)
            url = self._next_url(response)
        if url is not None:
            raise BasecampResponseError(f"More than {self._max_pages} pages; refusing to continue")
        return items

    def _url(self, path: str) -> str:
        return f"{self._config.base_url}/{path.lstrip('/')}"

    def _next_url(self, response: httpx.Response) -> Optional[str]:
        next_link = response.links.get("next", {}).get("url")
        if not next_link:
            return None
        parsed, api = urlparse(next_link), urlparse(API_ROOT)
        if parsed.scheme != api.scheme or parsed.netloc != api.netloc:
            raise BasecampResponseError("Pagination link points outside the Basecamp API (host or https)")
        return next_link

    def _request(self, url: str) -> httpx.Response:
        path = urlparse(url).path
        for attempt in range(1, self._max_attempts + 1):
            started = time.monotonic()
            last_attempt = attempt == self._max_attempts
            try:
                response = self._http.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                self._log_failure(path, attempt, started, None, "UpstreamUnavailable", type(exc).__name__)
                if last_attempt:
                    raise BasecampUnavailable(
                        f"Basecamp unreachable after {attempt} attempts ({type(exc).__name__})"
                    ) from None
                self._sleep(self._backoff(attempt))
                continue

            status = response.status_code
            if 200 <= status < 300:
                _log(logging.INFO, "basecamp_request_succeeded", method="GET", path=path, attempt=attempt,
                     status=status, duration_ms=_elapsed_ms(started), outcome="success")
                return response
            if status in (401, 403):
                self._log_failure(path, attempt, started, status, "AuthError")
                raise BasecampAuthError(
                    "Basecamp rejected the OAuth token (invalid, expired or lacking access)", status
                )
            if status == 429:
                self._log_failure(path, attempt, started, status, "RateLimitError")
                if last_attempt:
                    raise BasecampRateLimited(f"Basecamp rate limit still exceeded after {attempt} attempts", status)
                self._sleep(self._retry_after(response, attempt))
                continue
            if status >= 500:
                self._log_failure(path, attempt, started, status, "UpstreamUnavailable")
                if last_attempt:
                    raise BasecampUnavailable(f"Basecamp returned {status} after {attempt} attempts", status)
                self._sleep(self._backoff(attempt))
                continue
            self._log_failure(path, attempt, started, status, "ContractViolation")
            raise BasecampResponseError(f"Basecamp returned unexpected status {status}", status)
        raise AssertionError("unreachable")  # loop always returns or raises

    def _backoff(self, attempt: int) -> float:
        return self._backoff_s[min(attempt - 1, len(self._backoff_s) - 1)]

    def _retry_after(self, response: httpx.Response, attempt: int) -> float:
        raw = response.headers.get("Retry-After", "").strip()
        if raw.isdigit():
            return min(float(raw), self._max_retry_after_s)
        return self._backoff(attempt)

    def _log_failure(self, path: str, attempt: int, started: float, status: Optional[int],
                     error_class: str, cause: Optional[str] = None) -> None:
        _log(logging.WARNING, "basecamp_request_failed", method="GET", path=path, attempt=attempt,
             max_attempts=self._max_attempts, status=status, duration_ms=_elapsed_ms(started),
             outcome="failure", error_class=error_class, cause=cause)


def _parse_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise BasecampResponseError("Basecamp response was not valid JSON", response.status_code) from None


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _log(level: int, event: str, **context: Any) -> None:
    line = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": logging.getLevelName(level).lower(),
        "service": "backend",
        "event": event,
        **context,
    }
    logger.log(level, json.dumps(line))
