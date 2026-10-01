"""Images in the evaluation (user decision 2026-10-02), with a scripted fake
Claude and a fake image source: no network, no cost."""
import base64
from datetime import datetime, timezone

import pytest

from app.audit.trail import InMemoryAuditTrail
from app.basecamp.image_download import FetchedImage, ImageFetchError
from app.evaluation.claude_client import AnthropicEvaluator
from app.evaluation.config import EvaluationConfig
from app.evaluation.evaluate import evaluate_submission
from app.evaluation.fake import ScriptedEvaluator
from app.evaluation.store import ResultStore, UsageLedger
from app.models import ClaudeStageAnswer, Submission, SubmissionComment
from app.rules.loader import MODULES_DIR, RuleLoadResult
from app.rules.module import RuleModule

_NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
_V2 = RuleModule.model_validate_json((MODULES_DIR / "ST0" / "v2.json").read_text())
_RULES = RuleLoadResult(outcome="loaded", stress_test_id="ST0", rule_version="v2", module=_V2)
_STAGE_1 = ["ST0-001", "ST0-002", "ST0-003", "ST0-006", "ST0-007", "ST0-008"]
_STAGE_2 = ["ST0-004", "ST0-005"]
_CONFIG = EvaluationConfig(api_key="sk-ant-test-0000", max_tokens=1000, max_input_tokens=50_000, daily_token_limit=500_000)
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 16


def _img(name):
    return (f'<bc-attachment content-type="image/png" filename="{name}" '
            f'url="https://preview.3.basecamp.com/1/blobs/{name}"></bc-attachment>')


_HTML = (f"<div>Dataset Description: weekly sales</div><div>Data Source: https://kaggle.com/x</div>{_img('source.png')}"
         f"<div>Dataset Screenshot:</div>{_img('old.png')}{_img('shot.png')}<div>##Critique##</div>")


def _submission(html=_HTML):
    return Submission(message_id=500, title="Stress Test 0 - Dataset & DS Problem", created_at=_NOW, content_html="",
                      comments=[SubmissionComment(comment_id=2002, created_at=_NOW, content_html=html)])


def _answer(passed, findings=()):
    return ClaudeStageAnswer(passed_rule_ids=list(passed), findings=list(findings))


class FakeImages:
    def __init__(self, error=None):
        self.urls, self.error = [], error

    def __call__(self, attachment):
        self.urls.append(attachment.url)
        if self.error:
            raise ImageFetchError(self.error, "nope")
        return FetchedImage(media_type="image/png", data=_PNG)


@pytest.fixture
def env(tmp_path):
    return {"store": ResultStore(tmp_path), "ledger": UsageLedger(tmp_path, daily_limit=_CONFIG.daily_token_limit),
            "audit": InMemoryAuditTrail(), "config": _CONFIG, "clock": lambda: _NOW}


def _evaluate(claude, env, images, submission=None):
    return evaluate_submission(submission or _submission(), 2002, _RULES, evaluator=claude, images=images, **env)


def test_only_the_stage_with_the_image_rule_gets_only_the_screenshot_parts_last_image(env):
    claude, images = ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2)), FakeImages()
    result = _evaluate(claude, env, images)
    stage_1, stage_2 = claude.prompts
    assert stage_1.images == [] and "Images:" not in stage_1.user
    assert images.urls == ["https://preview.3.basecamp.com/1/blobs/shot.png"]  # not old.png, not source.png
    [image] = stage_2.images
    assert base64.b64decode(image.data_base64) == _PNG and image.media_type == "image/png"
    assert 'for ST0-004, from the part "Dataset Screenshot"' in image.caption
    assert "ST0-004: 1 image(s) attached above" in stage_2.user
    assert [(n.rule_id, n.filename, n.outcome) for n in result.images] == [("ST0-004", "shot.png", "READ")]
    events = [(e.action, e.rule_id, e.reason_code) for e in env["audit"].read_all()]
    assert ("evaluation_image", "ST0-004", "READ") in events


def test_when_stage_1_fails_no_image_is_downloaded(env):
    fail = {"rule_id": "ST0-002", "status": "FAIL", "severity": "Required Fix", "evidence": "e", "reason": "r",
            "suggested_feedback": "f", "confidence": 0.9}
    images = FakeImages()
    result = _evaluate(ScriptedEvaluator(_answer(_STAGE_1[:1] + _STAGE_1[2:], [fail])), env, images)
    assert images.urls == [] and result.images == [] and result.stages_evaluated == [1]


def test_an_image_that_cannot_be_read_is_reported_and_the_review_goes_on(env):
    claude = ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2))
    result = _evaluate(claude, env, FakeImages(error="TOKEN_REJECTED"))
    stage_2 = claude.prompts[1]
    assert stage_2.images == []
    assert "could not be read (TOKEN_REJECTED)" in stage_2.user and "ADVISORY" in stage_2.user
    assert [(n.outcome, n.filename) for n in result.images] == [("TOKEN_REJECTED", "shot.png")]
    events = [(e.action, e.outcome, e.reason_code) for e in env["audit"].read_all()]
    assert ("evaluation_image", "failure", "TOKEN_REJECTED") in events


def test_without_an_image_source_nothing_is_fetched_and_claude_is_told(env):
    claude = ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2))
    result = _evaluate(claude, env, None)
    assert "could not be read (NOT_FETCHED)" in claude.prompts[1].user
    assert [n.outcome for n in result.images] == ["NOT_FETCHED"]


def test_no_image_in_the_screenshot_part_means_none_attached_and_text_judging(env):
    claude, images = ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2)), FakeImages()
    html = f"<div>Data Source: https://kaggle.com/x</div>{_img('source.png')}<div>##Critique## problems below</div>"
    result = _evaluate(claude, env, images, _submission(html))
    assert images.urls == [] and result.images == []
    assert "ST0-004: no image sits in its part" in claude.prompts[1].user


def test_a_rerun_neither_downloads_again_nor_calls_claude(env):
    claude, images = ScriptedEvaluator(_answer(_STAGE_1), _answer(_STAGE_2)), FakeImages()
    first = _evaluate(claude, env, images)
    assert _evaluate(claude, env, images) == first
    assert len(images.urls) == 1 and len(claude.prompts) == 2


def test_the_v2_system_prompt_says_which_rule_gets_images_and_v1_is_unchanged():
    from app.evaluation.prompt import build_system_prompt
    v1 = RuleModule.model_validate_json((MODULES_DIR / "ST0" / "v1.json").read_text())
    assert "you cannot see its contents." in build_system_prompt(v1)
    assert "except images attached to the message for ST0-004" in build_system_prompt(_V2)


def test_the_claude_request_puts_each_caption_and_image_before_the_text():
    from app.evaluation.prompt import EvaluationPrompt, PromptImage
    plain = EvaluationPrompt(system="s", user="u")
    assert AnthropicEvaluator._content(plain) == "u"
    with_image = EvaluationPrompt(system="s", user="u", images=[PromptImage(media_type="image/png", data_base64="QQ==",
                                                                              caption="Image 1")])
    assert AnthropicEvaluator._content(with_image) == [
        {"type": "text", "text": "Image 1"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QQ=="}},
        {"type": "text", "text": "u"},
    ]
