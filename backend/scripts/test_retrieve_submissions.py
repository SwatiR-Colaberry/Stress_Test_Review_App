import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import retrieve_submissions  # noqa: E402

from app.basecamp.demo_data import DEMO_EMPTY_PROJECT, DEMO_PROJECT_WITH_SUBMISSIONS  # noqa: E402


def test_demo_project_prints_counts_only(capsys):
    code = retrieve_submissions.main(["--demo", "--project-id", str(DEMO_PROJECT_WITH_SUBMISSIONS), "--user-id", "r1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "DEMO MODE" in out
    assert "2 submissions" in out
    assert "message 301: 1 comments, 2 attachments, 2 links" in out
    assert "##Critique##" not in out  # content is never printed


def test_demo_empty_project_returns_zero_submissions(capsys):
    assert retrieve_submissions.main(["--demo", "--project-id", str(DEMO_EMPTY_PROJECT), "--user-id", "r1"]) == 0
    assert "0 submissions" in capsys.readouterr().out


def test_save_writes_the_dataset_and_rerun_overwrites_it(tmp_path):
    argv = ["--demo", "--project-id", str(DEMO_PROJECT_WITH_SUBMISSIONS), "--user-id", "r1", "--save"]
    assert retrieve_submissions.main(argv, output_dir=tmp_path) == 0
    assert retrieve_submissions.main(argv, output_dir=tmp_path) == 0
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == [f"demo_project_{DEMO_PROJECT_WITH_SUBMISSIONS}.json"]  # no duplicates, no temp files
    data = json.loads((tmp_path / files[0]).read_text())
    assert data["requested_by_user_id"] == "r1" and len(data["submissions"]) == 2


def test_unknown_project_says_not_found_or_not_visible(capsys):
    assert retrieve_submissions.main(["--demo", "--project-id", "555", "--user-id", "r1"]) == 4
    assert "NOT FOUND: project 555" in capsys.readouterr().out


def test_blank_user_id_is_an_input_error():
    assert retrieve_submissions.main(["--demo", "--project-id", "100", "--user-id", " "]) == 1


def test_live_mode_without_config_reports_missing_variables(monkeypatch, capsys):
    monkeypatch.setattr(retrieve_submissions, "load_dotenv", lambda *a, **k: None)
    for var in ["BASECAMP_ACCOUNT_ID", "BASECAMP_ACCESS_TOKEN", "BASECAMP_USER_AGENT"]:
        monkeypatch.delenv(var, raising=False)
    assert retrieve_submissions.main(["--project-id", "100", "--user-id", "r1"]) == 1
    assert "BASECAMP_ACCESS_TOKEN" in capsys.readouterr().out
