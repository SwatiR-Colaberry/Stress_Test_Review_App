"""Downloads one image a student embedded in Basecamp, for Claude to look at
(user decision 2026-10-02). The bytes stay in memory: never written to disk.

- Only https download links on the Basecamp API host (*.basecampapi.com,
  the download_url of an attachment: see image_source.py) are fetched, with
  the token. The API answers with a redirect to a pre-signed storage link
  (storage.basecamp.com); redirects are followed (at most MAX_REDIRECTS)
  WITHOUT the token: storage refuses a second credential (HTTP 400), and the
  token must never leave the API host. (The browser links in the comment
  HTML, preview.app.basecamp.com, need a Basecamp browser login: 404 with a
  token. Found in the first live run, 2026-10-02.)
- Timeout config.timeout_s per request. At most 3 attempts (waiting 1 s, then
  2 s) for a connection error, timeout, 429 or 5xx; 401/403 (token rejected or
  expired) and 404 are never retried.
- Types: PNG, JPEG, GIF, WebP, told by the file's first bytes (Claude's image
  types). Size: at most MAX_BYTES (Claude's 5 MB limit), checked while
  reading, so an oversized file is never read in full.
Every failure raises ImageFetchError with a reason code; the caller treats
the image as unreadable and the rule stays with the reviewer. One JSON log
line per image: outcome, reason, size, time. Never the URL (it can carry a
signed query) and never the token.
"""
import json
import logging
import time
from typing import Callable, Optional, Sequence
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel

from app.basecamp.config import BasecampConfig

logger = logging.getLogger("stress_test_review.basecamp")

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


class FetchedImage(BaseModel):
    media_type: str
    data: bytes


class ImageFetchError(Exception):
    """reason_code: BAD_URL, TOKEN_REJECTED, NOT_FOUND, TOO_LARGE, UNSUPPORTED_TYPE,
    UNAVAILABLE (retries used up) or BAD_RESPONSE."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def media_type_of(data: bytes) -> Optional[str]:
    for signature, media_type in _SIGNATURES:
        if data.startswith(signature):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _is_api(url: str) -> bool:
    return (urlparse(url).hostname or "").lower().endswith(".basecampapi.com")


class ImageDownloader:
    def __init__(self, config: BasecampConfig, transport: Optional[httpx.BaseTransport] = None,
                 max_attempts: int = 3, backoff_s: Sequence[float] = (1.0, 2.0),
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._config, self._transport = config, transport
        self._max_attempts, self._backoff_s, self._sleep = max_attempts, tuple(backoff_s), sleep

    def fetch(self, url: Optional[str]) -> FetchedImage:
        started = time.monotonic()
        try:
            image = self._fetch(url or "")
        except ImageFetchError as exc:
            self._log("image_fetch_failed", "failure", started, reason_code=exc.reason_code)
            raise
        self._log("image_fetched", "success", started, bytes=len(image.data), media_type=image.media_type)
        return image

    def _fetch(self, url: str) -> FetchedImage:
        if urlparse(url).scheme != "https" or not _is_api(url):
            raise ImageFetchError("BAD_URL", "only https download links on the Basecamp API are fetched")
        with httpx.Client(timeout=self._config.timeout_s, transport=self._transport, follow_redirects=False) as http:
            for _ in range(MAX_REDIRECTS + 1):
                headers = {"User-Agent": self._config.user_agent}
                if _is_api(url):
                    headers["Authorization"] = self._config.auth_headers()["Authorization"]
                status, location, data = self._get(http, url, headers)
                if status in (301, 302, 303, 307, 308):
                    url = urljoin(url, location or "")
                    if urlparse(url).scheme != "https":
                        raise ImageFetchError("BAD_URL", "redirected to a non-https address")
                    continue
                return self._image(data)
        raise ImageFetchError("BAD_RESPONSE", f"more than {MAX_REDIRECTS} redirects")

    def _get(self, http: httpx.Client, url: str, headers: dict):
        for attempt in range(1, self._max_attempts + 1):
            try:
                with http.stream("GET", url, headers=headers) as response:
                    status = response.status_code
                    if status in (401, 403):
                        raise ImageFetchError("TOKEN_REJECTED", f"Basecamp refused the token ({status})")
                    if status == 404:
                        raise ImageFetchError("NOT_FOUND", "the image is no longer on Basecamp")
                    if 300 <= status < 400:
                        return status, response.headers.get("location"), b""
                    if status == 200:
                        return status, None, self._read(response)
                    if status != 429 and status < 500:
                        raise ImageFetchError("BAD_RESPONSE", f"unexpected status {status}")
            except httpx.TransportError:
                pass  # connection error or timeout: retried below
            if attempt < self._max_attempts:
                self._sleep(self._backoff_s[min(attempt - 1, len(self._backoff_s) - 1)])
        raise ImageFetchError("UNAVAILABLE", f"Basecamp did not return the image after {self._max_attempts} attempts")

    @staticmethod
    def _read(response: httpx.Response) -> bytes:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            raise ImageFetchError("TOO_LARGE", f"image is over {MAX_BYTES // (1024 * 1024)} MB")
        chunks, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise ImageFetchError("TOO_LARGE", f"image is over {MAX_BYTES // (1024 * 1024)} MB")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _image(data: bytes) -> FetchedImage:
        media_type = media_type_of(data)
        if media_type is None:
            raise ImageFetchError("UNSUPPORTED_TYPE", "not a PNG, JPEG, GIF or WebP image")
        return FetchedImage(media_type=media_type, data=data)

    def _log(self, event: str, outcome: str, started: float, **context: object) -> None:
        logger.log(logging.INFO if outcome == "success" else logging.WARNING, json.dumps({
            "event": event, "service": "backend", "outcome": outcome,
            "duration_ms": round((time.monotonic() - started) * 1000), "context": context,
        }))
