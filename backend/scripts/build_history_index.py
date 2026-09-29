"""One-off operational script: build (or refresh) the historical-review
vector index (STORY-013) from a history extract.

Reads <extract>/comments.csv, pairs each student submission with the
reviewer's answer (app/history/cases.py), embeds the submissions locally
(fastembed, no key, nothing sent out; the model downloads once on first use)
and upserts them into the LanceDB index (default data/vector_index/,
git-ignored; HISTORY_INDEX_DIR overrides it). SQL Server is not touched.

Safe to run twice: cases are keyed on the submission's CommentId, so a re-run
replaces them and never adds duplicates. Batches are upserted one at a time;
if a run fails part-way, the batches already written stay, and re-running
completes the rest. Prints counts only, never student or reviewer text.

Run from the repo root:
  .venv/bin/python backend/scripts/build_history_index.py --extract data/extracts/2026-09-25-per-stress-test
Exit codes: 0 ok, 1 input problem (extract missing or unreadable),
3 embedding model or vector index unavailable.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.history.cases import load_cases_from_extract  # noqa: E402
from app.history.config import HistoryConfigError, load_history_config  # noqa: E402
from app.history.embedder import Embedder, EmbeddingError, FastEmbedEmbedder  # noqa: E402
from app.history.lancedb_index import LanceDbVectorIndex  # noqa: E402
from app.history.vector_index import IndexedCase, VectorIndex, VectorIndexError  # noqa: E402

BATCH_SIZE = 32
STRESS_TESTS = [f"ST{n}" for n in range(6)]


def main(argv: Optional[List[str]] = None, *, embedder: Optional[Embedder] = None,
         index: Optional[VectorIndex] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--extract", type=Path, required=True, help="folder holding comments.csv")
    args = parser.parse_args(argv)

    try:
        cases, skipped = load_cases_from_extract(args.extract)
    except (OSError, KeyError, ValueError) as exc:
        print(f"INPUT PROBLEM: cannot read {args.extract / 'comments.csv'}: {type(exc).__name__}")
        return 1
    if index is None:
        try:
            index = LanceDbVectorIndex(load_history_config().index_dir)
        except HistoryConfigError as exc:
            print(f"INPUT PROBLEM: {exc}")
            return 1
    embedder = embedder or FastEmbedEmbedder()

    per_test = Counter(case.stress_test_id for case in cases)
    print(f"{len(cases)} cases from {args.extract.name}: "
          + ", ".join(f"{st} {per_test[st]}" for st in STRESS_TESTS)
          + (f"; skipped (no text): {dict(skipped)}" if skipped else ""))
    try:
        for start in range(0, len(cases), BATCH_SIZE):
            batch = cases[start:start + BATCH_SIZE]
            vectors = embedder.embed([case.submission_excerpt for case in batch])
            index.upsert([IndexedCase(case=case, vector=vector) for case, vector in zip(batch, vectors)])
            print(f"  indexed {min(start + BATCH_SIZE, len(cases))}/{len(cases)}")
        counts = {st: index.count(st) for st in STRESS_TESTS} if cases else {}
    except (EmbeddingError, VectorIndexError) as exc:
        print(f"UNAVAILABLE ({exc.error_class}): {exc}. Batches already written are kept; re-run to finish.")
        return 3
    if counts:
        print("index now holds: " + ", ".join(f"{st} {n}" for st, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
