import httpx
import pytest
from pydantic import SecretStr

from app.basecamp.config import BasecampConfig
from app.basecamp.image_download import ImageFetchError
from app.basecamp.image_source import CommentImageSource
from app.models import SubmissionAttachment

PNG = b"\x89PNG\r\n\x1a\n" + b"\x02" * 32
CONFIG = BasecampConfig(account_id=99, access_token=SecretStr("tok-secret-456"), user_agent="Stress Test (x@example.com)")
COMMENT = "/99/buckets/7/comments/555.json"
SHOT = SubmissionAttachment(filename="shot.png", content_type="image/png", sgid="sg-shot",
                            url="https://preview.app.basecamp.com/99/blobs/k/previews/full")


def basecamp(calls, comment_status=200, attachments=None):
    """A fake Basecamp: the API comment, the API download link, the pre-signed storage link."""
    attachments = attachments if attachments is not None else [
        {"sgid": "sg-shot", "download_url": "https://3.basecampapi.com/99/blobs/k/download/shot.png"},
        {"sgid": "sg-other", "download_url": "https://3.basecampapi.com/99/blobs/o/download/o.png"}]

    def handler(request):
        calls.append((request.url.host, request.url.path, request.headers.get("authorization")))
        if request.url.path == COMMENT:
            return httpx.Response(comment_status, json={"id": 555, "content_attachments": attachments})
        if request.url.host == "3.basecampapi.com":
            return httpx.Response(302, headers={"location": "https://storage.basecamp.com/b?X-Amz-Signature=s"})
        return httpx.Response(200, content=PNG)
    return httpx.MockTransport(handler)


def source(calls, **kwargs):
    return CommentImageSource(CONFIG, 7, 555, transport=basecamp(calls, **kwargs), sleep=lambda s: None)


def test_the_picked_image_is_found_by_sgid_in_the_api_comment_and_downloaded():
    calls = []
    image = source(calls)(SHOT)
    assert image.data == PNG and image.media_type == "image/png"
    assert [(host, path) for host, path, _ in calls] == [
        ("3.basecampapi.com", COMMENT), ("3.basecampapi.com", "/99/blobs/k/download/shot.png"), ("storage.basecamp.com", "/b")]
    assert [auth is not None for _, _, auth in calls] == [True, True, False]  # never the token to storage


def test_the_comment_is_read_once_for_several_images():
    calls = []
    images = source(calls)
    images(SHOT)
    images(SHOT.model_copy(update={"sgid": "sg-other"}))
    assert sum(path == COMMENT for _, path, _ in calls) == 1


def test_an_image_the_api_does_not_list_is_not_found():
    calls = []
    with pytest.raises(ImageFetchError) as caught:
        source(calls)(SHOT.model_copy(update={"sgid": "sg-missing"}))
    assert caught.value.reason_code == "NOT_FOUND"
    with pytest.raises(ImageFetchError) as caught:
        source(calls, attachments=[])(SHOT.model_copy(update={"sgid": None}))
    assert caught.value.reason_code == "NOT_FOUND"


@pytest.mark.parametrize("status, reason", [(401, "TOKEN_REJECTED"), (503, "UNAVAILABLE"), (404, "BAD_RESPONSE")])
def test_a_comment_basecamp_will_not_give_is_one_reason_and_is_not_asked_again(status, reason):
    calls = []
    images = source(calls, comment_status=status)
    for _ in range(2):
        with pytest.raises(ImageFetchError) as caught:
            images(SHOT)
        assert caught.value.reason_code == reason
    asked = sum(path == COMMENT for _, path, _ in calls)
    assert asked == (3 if status == 503 else 1)  # retried within the first image only, never again
