"""live_trial.py with a fake database, a scripted fake Claude and no server:
no network, no key, no cost, nothing written outside tmp_path."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_trial  # noqa: E402

from app.audit import dependencies as audit_dependencies  # noqa: E402
from app.audit.trail import InMemoryAuditTrail  # noqa: E402
from app.db.connection import DatabaseConnectionError  # noqa: E402
from app.evaluation.fake import ScriptedEvaluator  # noqa: E402
from app.models import ClaudeStageAnswer  # noqa: E402
from app.review_queue import dependencies as queue_dependencies  # noqa: E402
from app.review_queue.store import InMemoryReviewQueueStore  # noqa: E402

_STEP = "Stress Test 0 - Dataset & DS Problem"
_SUBMISSION = "<div>Dataset: retail sales.</div><ul><li>Problem: churn</li><li>Solution: classify</li></ul>"


def _rows():
    def row(comment_id, minute, body, email="student@example.com"):
        return {"BCP_ID": 77, "StepName": _STEP, "MessageBoardURL": "https://3.basecamp.com/1/buckets/2/messages/3",
                "MessageId": 501, "CommentId": comment_id, "CommentCreatedDate": f"2026-10-01 10:{minute:02d}:00",
                "CreatorName": "Sam Student", "CreatorEmail": email, "Comment": body}
    return [row(1001, 1, "<div>first ##Critique##</div>"),
            row(1002, 2, "<div>Add a link ##FeedbackGiven##</div>", email="rev@example.com"),
            row(1003, 3, _SUBMISSION + "<div>##Critique##</div>")]


def _stage_1_fail():
    return ClaudeStageAnswer(passed_rule_ids=["ST0-001", "ST0-003", "ST0-006", "ST0-007", "ST0-008"], findings=[{
        "rule_id": "ST0-002", "status": "FAIL", "severity": "Required Fix", "evidence": "No link.",
        "reason": "ST0-002 needs one.", "suggested_feedback": "Please provide the public source link.",
        "confidence": 0.9}])


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    monkeypatch.setenv("EVALUATIONS_DIR", str(tmp_path / "evaluations"))
    queue, audit = InMemoryReviewQueueStore(), InMemoryAuditTrail()
    monkeypatch.setattr(queue_dependencies, "_store", queue)
    monkeypatch.setattr(audit_dependencies, "_trail", audit)
    monkeypatch.setattr(live_trial, "port_free", lambda port: True)
    return queue, audit, tmp_path


def _main(tmp_path, argv, evaluator=None, rows=_rows, served=None, images=None):
    return live_trial.main(argv, read_rows=rows, evaluator=evaluator,
                           run_server=(served.append if served is not None else lambda port: None),
                           env_file=tmp_path / "no.env", images=images or _no_images)


def _no_images(attachment):
    raise AssertionError("no image should be fetched in this test")


def test_without_yes_it_only_reports_ids_and_writes_nothing(stores, capsys):
    queue, audit, tmp_path = stores
    claude = ScriptedEvaluator()  # no answers: any call would fail the test
    assert _main(tmp_path, [], claude) == 0
    out = capsys.readouterr().out
    assert "comment 1003 in thread 501" in out and "--yes" in out
    assert "Sam Student" not in out and "student@example.com" not in out and "Dataset" not in out
    assert queue.list_items() == [] and claude.prompts == []


def test_with_yes_it_queues_drafts_and_serves_the_newest_request(stores, capsys):
    queue, audit, tmp_path = stores
    served = []
    assert _main(tmp_path, ["--yes"], ScriptedEvaluator(_stage_1_fail()), served=served) == 0
    [item] = queue.list_items()
    assert (item.comment_id, item.author_name) == (1003, "Sam Student")
    assert served == [8000]
    assert (tmp_path / "evaluations" / "results.jsonl").exists()
    out = capsys.readouterr().out
    assert "1 FAIL" in out and "Sam Student" not in out
    actions = [e.action for e in audit.read_all()]
    assert "review_created" in actions and "evaluation_completed" in actions


def test_running_twice_neither_duplicates_the_review_nor_pays_twice(stores):
    queue, audit, tmp_path = stores
    claude = ScriptedEvaluator(_stage_1_fail())  # one answer only: a second paid call would fail
    assert _main(tmp_path, ["--yes"], claude) == 0
    assert _main(tmp_path, ["--yes"], claude) == 0
    assert len(queue.list_items()) == 1 and len(claude.prompts) == 1


def test_a_database_outage_or_a_thread_without_a_request_stops_before_anything_is_written(stores, capsys):
    queue, audit, tmp_path = stores

    def down():
        raise DatabaseConnectionError("ConnectionTimeout", "HYT00", 3)
    assert _main(tmp_path, ["--yes"], rows=down) == 2
    assert _main(tmp_path, ["--yes"], rows=lambda: [_rows()[1]]) == 2
    assert queue.list_items() == []
    assert "DATABASE UNAVAILABLE" in capsys.readouterr().out


def test_a_busy_port_stops_before_anything_is_queued(stores, monkeypatch):
    queue, audit, tmp_path = stores
    monkeypatch.setattr(live_trial, "port_free", lambda port: False)
    assert _main(tmp_path, ["--yes"], ScriptedEvaluator()) == 3
    assert queue.list_items() == []


def test_a_failed_ai_draft_still_serves_the_queued_review(stores, capsys):
    from app.evaluation.claude_client import ClaudeUnavailableError
    queue, audit, tmp_path = stores
    served = []
    claude = ScriptedEvaluator(*[ClaudeUnavailableError("down")] * 5)
    assert _main(tmp_path, ["--yes"], claude, served=served) == 0
    assert len(queue.list_items()) == 1 and served == [8000]
    assert "queued without it" in capsys.readouterr().out


def test_the_env_file_key_wins_over_a_different_shell_key(stores, monkeypatch):
    """Found in the first live run: a key left in the shell by another project was used and refused."""
    import os

    from app.evaluation import config as evaluation_config
    queue, audit, tmp_path = stores
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-shell-key-from-another-project")
    env_file = tmp_path / "project.env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-project-key-from-dotenv\n")
    seen, real = {}, evaluation_config.load_evaluation_config

    def spy(environ=None):
        config = real(environ)
        seen["key"] = config.api_key.get_secret_value()
        return config
    monkeypatch.setattr(evaluation_config, "load_evaluation_config", spy)
    assert live_trial.main(["--yes"], read_rows=_rows, evaluator=ScriptedEvaluator(_stage_1_fail()),
                           run_server=lambda port: None, env_file=env_file) == 0
    assert seen == {"key": "sk-ant-project-key-from-dotenv"}
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-shell-key-from-another-project"  # shell left untouched


def test_the_screenshot_parts_image_is_fetched_for_st0_004_and_reported(stores, capsys):
    from app.basecamp.image_download import FetchedImage
    queue, audit, tmp_path = stores
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    shot = ('<div>Dataset Screenshot:</div><bc-attachment content-type="image/png" filename="shot.png" '
            'url="https://preview.3.basecamp.com/1/blobs/shot"></bc-attachment>')
    rows = lambda: [dict(_rows()[2], Comment=_SUBMISSION + shot + "<div>##Critique##</div>")]
    fetched = []
    claude = ScriptedEvaluator(ClaudeStageAnswer(passed_rule_ids=["ST0-001", "ST0-002", "ST0-003", "ST0-006", "ST0-007",
                                                                  "ST0-008"], findings=[]),
                               ClaudeStageAnswer(passed_rule_ids=["ST0-004", "ST0-005"], findings=[]))
    assert _main(tmp_path, ["--yes"], claude, rows=rows,
                 images=lambda a: fetched.append(a.url) or FetchedImage(media_type="image/png", data=png)) == 0
    assert fetched == ["https://preview.3.basecamp.com/1/blobs/shot"]
    assert len(claude.prompts[1].images) == 1
    out = capsys.readouterr().out
    assert "Image for ST0-004: READ" in out and "shot.png" not in out
