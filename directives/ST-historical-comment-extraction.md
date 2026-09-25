# ST0–ST5 Historical Comment Extraction

**Serves:** rule-building for the Stress Test modules — STORY-003 (REQ-003, load the ST0 rule module) and STORY-010 (REQ-017, ST1–ST5 as configuration). It also later feeds historical retrieval (Master Spec Phase 5). It reads the same table STORY-001 uses for live detection (REQ-001/REQ-002), and it is the first real use of SQL Server (REQ-013).

**Status (2026-09-25):** Steps 1–6 are done. The user approved 15 projects (BCP_ID 2148, 2075, 2083, 2427, 2275, 2333, 2311, 2281, 2264, 2058, 2071, 1803, 1779, 1778, 1272), which were extracted to `data/extracts/2026-09-25/` and verified OK. Next: use the extract to write the ST0 rule module (STORY-003).

## Goal

Pull the **complete** comment history for every active ST0–ST5 project: each submission, each `##Critique##`, each `##FeedbackGiven##`, each `##Approved##`, and the assigned critiquer. The rules for each Stress Test can then be derived from **what reviewers repeatedly asked students to fix**.

The chain is: Project → Stress Test step → Message board → Every comment → Marker (Critique / FeedbackGiven / Approved) → Critiquer.

## Why not `proc_AllStressTestData`

That procedure filters down to `Status = 'Critique'`. Rule-building needs the whole cycle (submission → critique → feedback → revision → approval), so it reads the underlying tables directly. Master Spec §5 makes the same point: the procedure stays for the existing Critique List and is not the authoritative source.

## The queries (`backend/app/basecamp/sql/`)

| File | Returns | Grain |
|---|---|---|
| `st_history_counts.sql` | Projects, threads and comments per Stress Test | one row per Stress Test |
| `st_history_comments.sql` | Project + COE + step + comment + SQL marker hint | **one row per `CommentId`** |
| `st_critiquer_assignments.sql` | Critiquer assignment history | one row per assignment record |
| `st_id_profile.sql` | ID and join-quality metrics (counts only) | one row per metric |
| `st_history_selection.sql` | The 15 projects with the richest review history (ids and counts only) | one row per project (`BCP_ID`) |

Tables: `ADF_CCS_BasecampProjects` (p), `ADF_CCS_BasecampProjects_Details` (pd), `ADF_CCS_CentersOfExcellence` (coe), `Basecamp_MessageBoards_MessageComments` (mc), `ADF_BasecampStressTestCritiquer` (sc). The steps link to the comments through `pd.MessageBoardID = mc.MessageId`.

### Decisions baked into the queries

1. **No `IsSubmitted` filter.** `IsSubmitted` is not a reliable version identifier (Master Spec §4). Every comment is kept, including those with `IsSubmitted = 1`. `test_no_query_filters_on_is_submitted` guards this.
2. **Critiquer history is a separate query.** Joining the critiquer table on `MessageId` alone repeats every comment once per assignment row. The two datasets are matched in Python instead: each comment takes the latest assignment on its thread made at or before the comment's `CreatedDate`. `test_comment_query_does_not_join_the_critiquer_table` guards this.
3. **Only real comments.** `st_history_comments.sql` INNER-joins the comments table, so a step with no comments produces no row (rather than a row with a NULL `CommentId`). Steps with zero comments still show up in the counts query.
4. **Identity.** `mc.CommentId` identifies the submission version and `mc.MessageId` identifies the thread. `mc.Id` (returned as `CommentRecordID`) is only a row id.
6. **No `IsActive` filter.** No project has `IsActive = 1` (NULL: 1,424, 0: 964), and `proc_AllStressTestData` doesn't filter on it either (its filter is commented out). The user confirmed that history doesn't need it. `test_no_query_filters_on_is_active` guards this.
7. **MessageId is joined as a number.** The types differ by table (`mc.MessageId` nvarchar(max), `pd.MessageBoardID` varchar(max), `sc.MessageId` bigint). All 62,064 comment `MessageId`s are numeric, so every join uses `TRY_CAST(... AS bigint)`. A stray non-numeric value (1 step has one) then drops out instead of failing the query, and the join avoids a slow text comparison. `test_message_ids_are_joined_as_numbers` guards this.
8. **One row per `CommentId`.** The comments table holds repeated snapshots of the same comment: 1,089 `CommentId`s over 4,714 rows, up to 8 each. They share the same `MessageId` and, in all but 3, the same text, and they differ mostly in `UpdatedDate` (sometimes `IsSubmitted`). The latest snapshot is kept (by `UpdatedDate`, then `Id`). `IsSubmittedAnyCopy` records whether any snapshot was marked Completed, and `CopiesOfComment` records how many snapshots existed. STORY-001's intake is already safe against this, because it is idempotent on `comment_id`.
5. **Markers.** The SQL `MarkerType` uses exact `LIKE` patterns. It is a hint, not authoritative (Master Spec §4.1): it depends on collation for case, it matches only a literal space, and when a comment carries two markers it reports only the first. Markers are recomputed in Python with `app.basecamp.critique_marker_detector`, and each disagreement with `MarkerType` is reported.

### Mapping to the app's `BasecampComment` model (STORY-001)

| SQL column | `BasecampComment` field |
|---|---|
| `mc.CommentId` | `comment_id` |
| `mc.MessageId` | `message_id` |
| `mc.Comment` | `body` |
| `mc.CreatedDate` | `created_at` |

`comment_id` and `message_id` must be positive integers. Step 3 confirms their real SQL types before any extraction.

## How the current process works (context for these rules)

The old Colaberry app's **Stress Test Grade** page runs `dbo.proc_AllStressTestData`. The procedure lists comments containing exactly `##Critique##` where `ISNULL(IsSubmitted,0) = 0` and `CreatedDate` falls within the last 3 months. The reviewer writes feedback in Basecamp (usually `##FeedbackGiven##`) and then clicks **Completed**, which (per the data: 6,569 of 6,583 `IsSubmitted = 1` rows are critique comments) sets `IsSubmitted = 1` on the critique comment so that it drops off the list. So `IsSubmitted` is the old app's "reviewer closed this" flag, not a version identifier. The new app never writes it.

## Selecting projects

History is extracted for a reviewed selection of projects, not for everything. `st_history_selection.sql` picks the 15 student projects (`BCP_ID`) whose Stress Test threads contain a **review cycle**, meaning a `##Critique##` later followed by `##FeedbackGiven##`. It ranks them by the number of different Stress Tests with a cycle (to spread the selection across ST0–ST5), then by the number of threads that reached `##Approved##`, then by the most recent activity. It returns ids and counts only. The user chose a whole project (all of its Stress Test threads) as the unit of selection, and 10–15 projects as the size.

## Order of operations

1. **Store the queries** (done).
2. **Local setup.** Install the Microsoft ODBC Driver 18 (`brew install msodbcsql18`) and add `pyodbc` to `requirements.txt`, following the connection method set in `docs/enterprise-portal-build-prompt.txt`. Copy `.env.example` to `.env` and fill in the values locally. Connection details come from IT/DBA (Master Spec §18) and **never** go into the repo, a commit, a log or a chat.
3. **Connection check.** Run `.venv/bin/python backend/scripts/check_db_connection.py` from the repo root. It loads `.env`, connects (with a login timeout, at most 3 attempts, and no retry after a rejected login), and reports: the server version and edition, whether Full-Text Search is installed, whether the login can INSERT into the comments table (it should not), every column of the five tables, any table or column the stored queries need but the database lacks, and whether `CommentId`/`MessageId` are integer types. Exit codes: 0 ok, 1 config, 2 connection, 3 schema. It prints no row data.
4. **Run `st_history_counts.sql`** and `backend/scripts/profile_st_ids.py`, then `backend/scripts/select_st_projects.py`. Review the numbers and the selection before going further.
5. **Run the extraction:** `.venv/bin/python backend/scripts/extract_st_history.py --bcp-ids <approved ids>`. It runs `st_history_comments.sql` and `st_critiquer_assignments.sql`, both restricted to the approved `BCP_ID`s through the `/*BCP_ID_FILTER*/` marker (the ids are bound as `?` parameters and never pasted into the SQL). It writes `comments.csv`, `critiquer_assignments.csv` and `summary.json` (counts only) to `data/extracts/<YYYY-MM-DD>/`. The files are written atomically, so a re-run on the same day overwrites them cleanly. It also runs `st_history_steps.sql`, which returns one row per step with its `StepHTML` (kept out of the comment rows, where it repeated on every comment; join on `ProjectDetailID`), and writes it to `steps.csv`. Exit codes: 0 ok, 1 config/arguments, 2 connection, 4 query, 5 verification failed.

**Timing.** Each query *executes* in about 1 s. Most of a run is *fetching* the rows: roughly 150–200 KB/s from this server, varying from run to run, so 10–60 s for the ~8 MB comments file. Every query logs `db_query_completed` with `execute_ms` (bounded by `DB_QUERY_TIMEOUT_S`) and `duration_ms` (execute plus fetch). The query timeout does not cover the fetch, so a slow link will not hit it. The earlier assumption that the de-duplication window was the slow part was measured and was wrong: the window takes 0.4 s.
6. **Verify the extract** (see below).

## Safety rules

- **Read-only.** Only `SELECT`. `test_queries_are_read_only` rejects any stored query that contains a write or `EXEC`. Use a least-privilege login (Master Spec §18) if IT can provide one.
- **Bounded.** Every connection and every query gets an explicit timeout. Retries are capped (the same policy as `fetch_with_retry`: at most 3 attempts), and a failure surfaces as a visible error.
- **Personal data.** Extracts contain student and reviewer names, emails and submission text. They are written only under `data/extracts/`, which `.gitignore` excludes. **Never commit an extract** (this repo is public), and never paste rows into docs, tickets or chats. Aggregates (counts, rule patterns) may be shared.
- **Size.** `StepHTML` and `Comment` are large text columns. Always run the counts query first.

## How success is verified (Step 6)

`extract_st_history.py` computes these checks, prints them and stores them in `summary.json`. `comments.csv` gains five columns: `StressTest`, `PyMarkers` (every marker the Python normalizer finds, `|`-separated), `MarkerAgrees` (whether the first Python marker equals the SQL `MarkerType`), `AssignedCritiquer` (the latest assignment on the thread at or before the comment) and `ThreadCritiquer` (the latest assignment on the thread overall). The run fails verification (exit 5) if any `CommentId` repeats, any requested project is missing, or any comment's `ProjectDetailID` is missing from `steps.csv`. The CSV files are created readable by the owner only (mode 600).

First run (2026-09-25, 15 projects): 1,450 comments, 0 duplicates, 15/15 projects, 87 threads. By Stress Test: ST0 108, ST1 176, ST2 818, ST3 146, ST4 101, ST5 101. Markers: 544 Critique, 439 FeedbackGiven, 94 Approved, 377 none. 0 marker disagreements; 4 comments carry two markers. 82 critiquer assignments. 1,395 comments have a thread critiquer, and 1,293 have one assigned at or before the comment.


- The number of distinct `CommentId`s in the extract equals the `Comments` total from the counts query (summed across Stress Tests).
- No `CommentId` appears twice in the comments extract.
- Every comment has a `MessageId` that is present in the `pd.MessageBoardID` scope.
- The Python markers are compared with the SQL `MarkerType`, and every disagreement is listed (these are expected where the Python normalizer is broader: case, or a comment with two markers).
- Every comment is matched to zero or one critiquer assignment, never more than one.

## Known caveats

- `'Stress Test 1%'` also matches a step named `Stress Test 1x…` (for example "Stress Test 10"). Check the counts output for unexpected step names.
- `LEFT(pd.StepName, 13)` assumes the step names start with exactly "Stress Test N". One step starts with a list number (`1.<tab>Stress Test 1…`) and is therefore not matched.
- `StepName` embeds student project titles, some of which contain first names. Treat it as personal data: print counts, never names.
- Full-Text Search is **not** installed on this server (SQL Server 2017, Web Edition). The Phase 5 historical retrieval cannot assume it.
- The sizing query counts only `IsActive = 1` projects. Inactive projects hold history too, and including them is a separate decision.
