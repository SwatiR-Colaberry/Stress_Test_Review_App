"""The images of one Basecamp comment, for Claude (user decision 2026-10-02).

The comment HTML kept in SQL Server only has browser links for its images
(preview.app.basecamp.com), which need a Basecamp browser login. Basecamp's
API copy of the same comment lists every attachment in content_attachments,
each with a download_url on the API host. So, for one comment:
  1. GET /buckets/{bucket}/comments/{comment}.json once, through
     BasecampClient (15 s timeout, at most 3 attempts), on the first image
     asked for; the answer (or its failure) is kept for the other images;
  2. match the picked image by its sgid (the same in the HTML and the API);
  3. download it with ImageDownloader (token to the API host only).
Every failure is an ImageFetchError with a reason code: TOKEN_REJECTED,
UNAVAILABLE, BAD_RESPONSE, NOT_FOUND (no such image in the API answer), plus
the downloader's own. The caller then leaves the rule to the reviewer.
"""
from typing import Callable, Dict, Optional

import httpx

from app.basecamp.api_client import (BasecampAuthError, BasecampClient, BasecampError, BasecampRateLimited,
                                     BasecampUnavailable)
from app.basecamp.config import BasecampConfig
from app.basecamp.image_download import FetchedImage, ImageDownloader, ImageFetchError
from app.models import SubmissionAttachment


class CommentImageSource:
    def __init__(self, config: BasecampConfig, bucket_id: int, comment_id: int,
                 transport: Optional[httpx.BaseTransport] = None, sleep: Optional[Callable[[float], None]] = None) -> None:
        self._config, self._bucket_id, self._comment_id = config, bucket_id, comment_id
        self._transport, self._sleep = transport, sleep
        self._downloader = ImageDownloader(config, transport=transport, **({"sleep": sleep} if sleep else {}))
        self._links: Optional[Dict[str, str]] = None
        self._error: Optional[ImageFetchError] = None

    def __call__(self, attachment: SubmissionAttachment) -> FetchedImage:
        url = self._download_links().get(attachment.sgid or "")
        if not url:
            raise ImageFetchError("NOT_FOUND", "Basecamp's copy of the comment does not list this image")
        return self._downloader.fetch(url)

    def _download_links(self) -> Dict[str, str]:
        if self._error is not None:
            raise self._error
        if self._links is None:
            try:
                self._links = self._read_links()
            except ImageFetchError as error:
                self._error = error
                raise
        return self._links

    def _read_links(self) -> Dict[str, str]:
        path = f"/buckets/{self._bucket_id}/comments/{self._comment_id}.json"
        try:
            with BasecampClient(self._config, transport=self._transport,
                                **({"sleep": self._sleep} if self._sleep else {})) as client:
                comment = client.get_json(path)
        except BasecampAuthError:
            raise ImageFetchError("TOKEN_REJECTED", "Basecamp refused the token") from None
        except (BasecampUnavailable, BasecampRateLimited):
            raise ImageFetchError("UNAVAILABLE", "Basecamp did not return the comment") from None
        except BasecampError:
            raise ImageFetchError("BAD_RESPONSE", "Basecamp returned an unexpected comment") from None
        attachments = comment.get("content_attachments") if isinstance(comment, dict) else None
        return {item["sgid"]: item["download_url"] for item in attachments or []
                if isinstance(item, dict) and isinstance(item.get("sgid"), str)
                and isinstance(item.get("download_url"), str)}
