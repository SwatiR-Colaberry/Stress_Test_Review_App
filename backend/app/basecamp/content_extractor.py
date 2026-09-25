"""Pulls attachments and links out of Basecamp rich-text HTML (REQ-004).

Basecamp returns message and comment bodies as HTML. Files appear as
<bc-attachment ...> tags; links appear as <a href="...">. This module is pure
(no I/O) and never raises on malformed HTML: html.parser is lenient, and a body
it cannot make sense of simply yields fewer items.

Rules:
- A <bc-attachment> whose content-type is a Basecamp mention
  (application/vnd.basecamp.mention) is a person, not a file, and is skipped.
- Only http/https links are kept. javascript:, mailto:, relative and empty
  hrefs are dropped, so nothing unsafe is handed to a reviewer as a link.
- Links are de-duplicated by URL, keeping the first occurrence, so the same
  body always gives the same list in the same order.
"""
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.models import SubmissionAttachment, SubmissionLink

_MENTION_CONTENT_TYPE = "application/vnd.basecamp.mention"
_ALLOWED_LINK_SCHEMES = ("http", "https")


def extract_attachments_and_links(
    html: Optional[str],
) -> Tuple[List[SubmissionAttachment], List[SubmissionLink]]:
    if not isinstance(html, str) or not html:
        return [], []
    parser = _ContentParser()
    parser.feed(html)
    parser.close()
    return parser.attachments, parser.links


class _ContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.attachments: List[SubmissionAttachment] = []
        self.links: List[SubmissionLink] = []
        self._seen_urls: set = set()
        self._open_link: Optional[Dict[str, str]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = {name: (value or "") for name, value in attrs}
        if tag == "bc-attachment":
            self._add_attachment(values)
        elif tag == "a":
            self._open_link = {"url": values.get("href", "").strip(), "text": ""}

    def handle_data(self, data: str) -> None:
        if self._open_link is not None:
            self._open_link["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._open_link is not None:
            self._add_link(self._open_link["url"], self._open_link["text"].strip())
            self._open_link = None

    def close(self) -> None:
        super().close()
        if self._open_link is not None:  # unclosed <a> at end of body
            self._add_link(self._open_link["url"], self._open_link["text"].strip())
            self._open_link = None

    def _add_attachment(self, values: Dict[str, str]) -> None:
        content_type = values.get("content-type") or None
        if content_type == _MENTION_CONTENT_TYPE:
            return
        self.attachments.append(
            SubmissionAttachment(
                filename=values.get("filename") or None,
                content_type=content_type,
                url=values.get("url") or values.get("href") or None,
                sgid=values.get("sgid") or None,
            )
        )

    def _add_link(self, url: str, text: str) -> None:
        if urlparse(url).scheme.lower() not in _ALLOWED_LINK_SCHEMES or url in self._seen_urls:
            return
        self._seen_urls.add(url)
        self.links.append(SubmissionLink(url=url, text=text))
