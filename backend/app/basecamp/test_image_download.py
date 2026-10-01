import httpx
import pytest
from pydantic import SecretStr

from app.basecamp.config import BasecampConfig
from app.basecamp.image_download import MAX_BYTES, ImageDownloader, ImageFetchError, media_type_of

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
URL = "https://3.basecampapi.com/1/blobs/abc/download/shot.png"
CONFIG = BasecampConfig(account_id=1, access_token=SecretStr("tok-secret-123"), user_agent="Stress Test (x@example.com)")


def downloader(handler, **kwargs):
    return ImageDownloader(CONFIG, transport=httpx.MockTransport(handler), sleep=lambda s: None, **kwargs)


def test_a_basecamp_image_is_fetched_with_the_token_and_typed_by_its_bytes():
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, content=PNG, headers={"content-type": "application/octet-stream"})
    image = downloader(handler).fetch(URL)
    assert (image.media_type, image.data) == ("image/png", PNG)
    assert seen == ["Bearer tok-secret-123"]


def test_the_redirect_to_presigned_storage_is_followed_without_the_token():
    """As Basecamp does it (live, 2026-10-02): the API redirects to storage.basecamp.com,
    which answers 400 if the token is sent along."""
    seen = []

    def handler(request):
        seen.append((request.url.host, request.headers.get("authorization")))
        if request.url.host == "3.basecampapi.com":
            return httpx.Response(302, headers={"location": "https://storage.basecamp.com/blob?X-Amz-Signature=abc"})
        if request.headers.get("authorization"):
            return httpx.Response(400)
        return httpx.Response(200, content=PNG)
    assert downloader(handler).fetch(URL).media_type == "image/png"
    assert seen == [("3.basecampapi.com", "Bearer tok-secret-123"), ("storage.basecamp.com", None)]


@pytest.mark.parametrize("url", [None, "", "http://3.basecampapi.com/x", "https://evil.example/x.png",
                                 "https://basecampapi.com.evil.example/x",
                                 "https://preview.app.basecamp.com/1/blobs/k/previews/full",  # browser-only link
                                 "https://storage.basecamp.com/blob"])
def test_only_https_download_links_on_the_basecamp_api_are_fetched(url):
    calls = []
    with pytest.raises(ImageFetchError) as caught:
        downloader(lambda r: calls.append(r) or httpx.Response(200, content=PNG)).fetch(url)
    assert caught.value.reason_code == "BAD_URL" and calls == []


@pytest.mark.parametrize("status,reason", [(401, "TOKEN_REJECTED"), (403, "TOKEN_REJECTED"), (404, "NOT_FOUND"),
                                           (400, "BAD_RESPONSE")])
def test_refusals_are_not_retried(status, reason):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status)
    with pytest.raises(ImageFetchError) as caught:
        downloader(handler).fetch(URL)
    assert caught.value.reason_code == reason and len(calls) == 1


def test_outages_are_retried_at_most_three_times_then_given_up():
    calls, waits = [], []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(503)
    d = ImageDownloader(CONFIG, transport=httpx.MockTransport(handler), sleep=waits.append)
    with pytest.raises(ImageFetchError) as caught:
        d.fetch(URL)
    assert caught.value.reason_code == "UNAVAILABLE" and len(calls) == 3 and waits == [1.0, 2.0]


def test_a_429_then_success_is_retried_once():
    replies = iter([httpx.Response(429), httpx.Response(200, content=PNG)])
    assert downloader(lambda r: next(replies)).fetch(URL).media_type == "image/png"


def test_too_large_images_are_refused_by_header_or_while_reading():
    with pytest.raises(ImageFetchError) as caught:
        downloader(lambda r: httpx.Response(200, content=PNG, headers={"content-length": str(MAX_BYTES + 1)})).fetch(URL)
    assert caught.value.reason_code == "TOO_LARGE"
    big = PNG + b"\x00" * MAX_BYTES
    with pytest.raises(ImageFetchError) as caught:
        downloader(lambda r: httpx.Response(200, content=big)).fetch(URL)
    assert caught.value.reason_code == "TOO_LARGE"


def test_non_images_and_endless_redirects_are_refused():
    with pytest.raises(ImageFetchError) as caught:
        downloader(lambda r: httpx.Response(200, content=b"<html>login</html>")).fetch(URL)
    assert caught.value.reason_code == "UNSUPPORTED_TYPE"
    with pytest.raises(ImageFetchError) as caught:
        downloader(lambda r: httpx.Response(302, headers={"location": URL})).fetch(URL)
    assert caught.value.reason_code == "BAD_RESPONSE"


def test_image_types_are_told_by_their_first_bytes():
    assert media_type_of(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert media_type_of(b"GIF89a...") == "image/gif"
    assert media_type_of(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert media_type_of(b"%PDF-1.7") is None


def test_logs_never_carry_the_url_or_the_token(caplog):
    with caplog.at_level("INFO", logger="stress_test_review.basecamp"):
        downloader(lambda r: httpx.Response(200, content=PNG)).fetch(URL + "?sig=SIGNED")
        with pytest.raises(ImageFetchError):
            downloader(lambda r: httpx.Response(401)).fetch(URL)
    text = caplog.text
    assert "image_fetched" in text and "TOKEN_REJECTED" in text
    assert "tok-secret-123" not in text and "SIGNED" not in text and "previews" not in text
