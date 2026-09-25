import importlib.util
import subprocess
from pathlib import Path

_spec = importlib.util.spec_from_file_location("scan_for_credentials", Path(__file__).parent / "scan_for_credentials.py")
scanner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scanner)


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text(".env\ndata/extracts/\n")
    (tmp_path / ".env").write_text("DB_PASSWORD=x\n")
    (tmp_path / "app.py").write_text("print(1)\n")
    (tmp_path / "data" / "extracts").mkdir(parents=True)
    (tmp_path / "data" / "extracts" / "comments.csv").write_text("a\n")
    return tmp_path


def test_git_ignored_files_are_reported_and_normal_files_are_not(tmp_path):
    repo = _repo(tmp_path)
    paths = [str(repo / ".env"), str(repo / "app.py"), str(repo / "data" / "extracts" / "comments.csv")]
    assert scanner._git_ignored(paths, repo_root=str(repo)) == {paths[0], paths[2]}


def test_a_tracked_file_is_scanned_even_if_it_matches_an_ignore_pattern(tmp_path):
    repo = _repo(tmp_path)
    subprocess.run(["git", "add", "-f", ".env"], cwd=repo, check=True)
    assert scanner._git_ignored([str(repo / ".env")], repo_root=str(repo)) == set()


def test_outside_a_git_repo_nothing_is_skipped(tmp_path):
    (tmp_path / "x.py").write_text("")
    assert scanner._git_ignored([str(tmp_path / "x.py")], repo_root=str(tmp_path)) == set()
