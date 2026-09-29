"""STORY-013: the index build script, with a stub embedder and a temp index."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_history_index  # noqa: E402

from app.history.embedder import Embedder, EmbeddingError  # noqa: E402
from app.history.lancedb_index import LanceDbVectorIndex  # noqa: E402

FIELDS = ["StressTest", "MessageId", "CommentId", "CommentCreatedDate", "CreatorEmail", "Comment"]
PRIVATE = "PRIVATE-STUDENT-TEXT"


class StubEmbedder(Embedder):
    def __init__(self, fail=False):
        self.fail = fail

    def embed(self, texts):
        if self.fail:
            raise EmbeddingError("embedding model load failed after 3 attempts: OSError")
        return [[1.0, float(len(t) % 7)] for t in texts]


def write_extract(folder: Path) -> Path:
    folder.mkdir()
    rows = []
    for n, st in enumerate(["0", "0", "3"]):
        rows.append([st, str(n), str(100 + n), "2026-01-01", "s@example.org", f"##Critique## {PRIVATE} {n}"])
        rows.append([st, str(n), str(200 + n), "2026-01-02", "r@example.org", "##FeedbackGiven## fix it"])
    with open(folder / "comments.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    return folder


def test_builds_the_index_and_prints_counts_only(tmp_path, capsys):
    index = LanceDbVectorIndex(tmp_path / "vi", backoff_s=0)
    code = build_history_index.main(["--extract", str(write_extract(tmp_path / "x"))],
                                    embedder=StubEmbedder(), index=index)
    out = capsys.readouterr().out
    assert code == 0
    assert "3 cases from x: ST0 2, ST1 0, ST2 0, ST3 1" in out
    assert "index now holds: ST0 2, ST1 0, ST2 0, ST3 1, ST4 0, ST5 0" in out
    assert PRIVATE not in out and "@example.org" not in out


def test_running_twice_does_not_duplicate(tmp_path, capsys):
    index = LanceDbVectorIndex(tmp_path / "vi", backoff_s=0)
    argv = ["--extract", str(write_extract(tmp_path / "x"))]
    assert build_history_index.main(argv, embedder=StubEmbedder(), index=index) == 0
    assert build_history_index.main(argv, embedder=StubEmbedder(), index=index) == 0
    assert index.count("ST0") == 2 and index.count("ST3") == 1


def test_embedding_unavailable_exits_3_with_the_cause(tmp_path, capsys):
    code = build_history_index.main(["--extract", str(write_extract(tmp_path / "x"))],
                                    embedder=StubEmbedder(fail=True), index=LanceDbVectorIndex(tmp_path / "vi"))
    assert code == 3
    assert "UNAVAILABLE (EmbeddingUnavailable)" in capsys.readouterr().out


def test_a_missing_extract_exits_1(tmp_path, capsys):
    code = build_history_index.main(["--extract", str(tmp_path / "nope")], embedder=StubEmbedder(),
                                    index=LanceDbVectorIndex(tmp_path / "vi"))
    assert code == 1 and "INPUT PROBLEM" in capsys.readouterr().out
