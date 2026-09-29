# Historical retrieval (STORY-013, REQ-019)

**Goal:** when Claude drafts a review, it sees how human reviewers answered similar past submissions of the **same Stress Test**, so feedback stays consistent. The examples never decide anything: the Stress Test rule module does.

**Status:** built 2026-09-28/29 (session CC-20260928-hwh9). First index: the per-Stress-Test history extract. Completed reviews from this app are added later (STORY-007).

## How it works

1. **Cases** (`backend/app/history/cases.py`): one case per review round in a thread: the student's last `##Critique##` comment before the reviewer's `##FeedbackGiven##` / `##Approved##` answer. Markers are read from the comment text, never from the extract's `MarkerType` column. A reviewer reply quoting `##Critique##`, or a bare `##Critique##` posted by the reviewer, is not a submission. Texts are plain text, review markers removed, cut to 2,000 characters. `case_id` = the submission's Basecamp `CommentId`.
2. **Embeddings** (`backend/app/history/embedder.py`): `BAAI/bge-small-en-v1.5` run **locally** with fastembed. No key, no paid service, student text never leaves the machine. The model (~67 MB) downloads once, on first use, to `~/.cache/stress-test-review/fastembed`.
3. **Vector database** (`backend/app/history/lancedb_index.py`): LanceDB, embedded, files in `data/vector_index/` (git-ignored: it holds student and reviewer text). **Not SQL Server**, which stays read-only.
4. **Retrieval** (`backend/app/history/retrieval.py`): filter to the submission's Stress Test, **then** rank by cosine similarity, return the top `HISTORY_TOP_K` (default 10, at most 15).
5. **Evaluation** (`backend/app/evaluation/evaluate.py`, `prompt.py`): one lookup per submission. Found cases go into the Claude user message before the submission, labelled "NOT rules", with each text cut to 600 characters. The system prompt (the rules) is unchanged. The outcome is stored on `EvaluationResult.history` and audited as `history_retrieved`.

## Settings (`.env`, optional)

| Variable | Default | Allowed |
|---|---|---|
| `HISTORY_TOP_K` | 10 | 1–15 |
| `HISTORY_INDEX_DIR` | `data/vector_index/` | any folder; keep it git-ignored |

## Build or refresh the index

```
.venv/bin/python backend/scripts/build_history_index.py --extract data/extracts/2026-09-25-per-stress-test
```

It prints counts only. It is safe to re-run: cases are replaced, never duplicated. If a run stops part-way, re-run it to finish. Exit codes: 0 ok, 1 extract missing or unreadable, 3 embedding model or index unavailable.

Expected with the 2026-09-25 extract: 472 cases (ST0 38, ST1 49, ST2 282, ST3 37, ST4 29, ST5 37), 7 rounds skipped for empty text.

## Failure modes

| What fails | What happens | Retries | Recovery |
|---|---|---|---|
| Embedding model cannot load (no network on first use, corrupt cache) | `unavailable` / `EmbeddingUnavailable`; the review continues without examples, and the reviewer sees the message | 3 attempts, 120 s each for loading, 30 s for embedding | fix the network or delete the cache folder, then the next review loads it again |
| Index never built | `unavailable` / `VectorIndexUnavailable` ("has not been built yet"), no retry | none (permanent) | run the build script |
| Index unreadable, slow or damaged | `unavailable` / `VectorIndexUnavailable` | 3 attempts, 10 s each | re-run the build script (it rewrites the cases) |
| Index returns another Stress Test's case | `unavailable` / `ContractViolation`: never quietly filtered | none | treat as a bug |
| Lookup raises anything else | `unavailable` / `HistoryLookupFailed`; the class is logged | none | treat as a bug |
| Nothing indexed for the Stress Test, or blank submission | `none_found`: empty list, "No similar past reviews: …" | n/a | index more history |

Not handled: evaluations stored before STORY-013 keep `history: null` (a replay returns the stored result). Images and attachments are only their `[image: name]` markers, not their content.

## Verify

1. `.venv/bin/python -m pytest backend/app/history backend/app/evaluation/test_evaluate_history.py backend/scripts/test_build_history_index.py -q`: all pass.
2. Build the index (above), twice. The counts must be identical.
3. `.venv/bin/python backend/scripts/history_demo.py 2>/dev/null` shows:
   - ST0 → 10 ST0 cases;
   - the same text as ST3 → ST3 only;
   - a missing index → `unavailable` with the reviewer message, and the evaluation completes;
   - an empty Stress Test → `none_found`;
   - the Trust checks all `True`.

   It uses a fake Claude and costs nothing.
