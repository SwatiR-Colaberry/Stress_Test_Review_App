-- Full ST0-ST5 comment history: one row per Basecamp comment (CommentId),
-- with its project, COE and Stress Test step. Read-only.
-- See directives/ST-historical-comment-extraction.md.
--
-- Differences from the query as originally provided (deliberate):
--   1. The ADF_BasecampStressTestCritiquer join and its columns are removed.
--      Joined on MessageId alone, a thread with several critiquer rows would
--      repeat every comment once per row. Critiquer history is extracted
--      separately (st_critiquer_assignments.sql) and matched in Python.
--   2. The comments join is INNER (was LEFT). A step with no comments would
--      otherwise produce a row with a NULL CommentId, which is not a comment.
--      Steps with zero comments are still visible in st_history_counts.sql.
--   3. No IsActive filter: no project has IsActive = 1 (NULL or 0 only), and
--      proc_AllStressTestData does not filter on it either (user-confirmed).
--   4. MessageId is joined as numbers. The column types differ across tables
--      (nvarchar/varchar/bigint); every value was profiled as numeric.
--   5. One row per CommentId. The comments table holds repeated snapshots of
--      the same comment (1,089 CommentIds over 4,714 rows, 2026-09-25): same
--      MessageId, text identical in all but 3, differing mostly in UpdatedDate
--      and sometimes IsSubmitted. The latest snapshot is kept (UpdatedDate,
--      then Id); IsSubmittedAnyCopy = 1 if any snapshot was marked Completed;
--      CopiesOfComment shows how many snapshots existed. Rows with a NULL
--      CommentId are excluded: without an id a row is not a comment version,
--      and ranking would otherwise collapse all of them into one partition.
--   6. pd.StepHTML is NOT returned here. It is the step's full HTML page;
--      repeated on every comment of its thread it made up 9 MB of a 16 MB
--      extract (0.5 MB unique). It is extracted once per step by
--      st_history_steps.sql; join on ProjectDetailID.
-- Everything else is as provided. In particular:
--   - NO "ISNULL(mc.IsSubmitted,0) = 0" filter: IsSubmitted is not a reliable
--     version identifier (Master Spec §4). All comments are kept.
--   - Version identity is mc.CommentId; thread identity is mc.MessageId.
--     mc.Id (CommentRecordID) is a row id, NOT the version id.
--   - MarkerType is an exact-LIKE hint only (Master Spec §4.1: not
--     authoritative). Markers are recomputed in Python with
--     app.basecamp.critique_marker_detector and compared against it.

SELECT
    -- Project information
    p.BCP_ID,
    p.UserID,
    p.BCP_Name,
    p.COE_ID,
    p.PTP_ID,
    p.ProjectNumber,
    p.ProjectSD,
    p.LastUpdated AS ProjectLastUpdated,
    p.ProjectID,
    p.IsActive,

    -- COE
    coe.COE_Name,

    -- Stress Test / Step information
    pd.ID AS ProjectDetailID,
    pd.PQ_ProjectID,
    pd.StepName,
    pd.PQ_Order,
    pd.StepType,
    pd.DueDate,
    pd.ProjectID AS DetailProjectID,
    pd.ListGroupID,
    pd.ListID,
    pd.ListURL,
    pd.TaskID,
    pd.TaskURL,
    pd.MessageBoardID,
    pd.MessageBoardURL,
    pd.StartDate,
    pd.LastUpdated AS StepLastUpdated,
    pd.LastUpdatedBy,
    pd.TaskCompleted,
    pd.TaskCompleteDate,
    pd.TaskDueDate,

    -- Comment / submission / feedback history
    mc.Id AS CommentRecordID,
    mc.MessageId,
    mc.CommentId,
    mc.Status AS CommentStatus,
    mc.Title,
    mc.CreatedDate AS CommentCreatedDate,
    mc.UpdatedDate AS CommentUpdatedDate,
    mc.CreatorName,
    mc.CreatorEmail,
    mc.Comment,
    mc.IsSubmitted,
    mc.IsSubmittedAnyCopy,
    mc.CopiesOfComment,

    -- Detect review markers (hint only; see header)
    CASE
        WHEN mc.Comment LIKE '%##Critique##%'
          OR mc.Comment LIKE '%## Critique##%'
          OR mc.Comment LIKE '%##Critique ##%'
          OR mc.Comment LIKE '%## Critique ##%'
        THEN 'Critique'

        WHEN mc.Comment LIKE '%##FeedbackGiven##%'
          OR mc.Comment LIKE '%## FeedbackGiven##%'
          OR mc.Comment LIKE '%##FeedbackGiven ##%'
          OR mc.Comment LIKE '%## FeedbackGiven ##%'
        THEN 'FeedbackGiven'

        WHEN mc.Comment LIKE '%##Approved##%'
          OR mc.Comment LIKE '%## Approved##%'
          OR mc.Comment LIKE '%##Approved ##%'
          OR mc.Comment LIKE '%## Approved ##%'
        THEN 'Approved'

        ELSE NULL
    END AS MarkerType

FROM dbo.ADF_CCS_BasecampProjects p

INNER JOIN dbo.ADF_CCS_BasecampProjects_Details pd
    ON p.BCP_ID = pd.BCP_ID

LEFT JOIN dbo.ADF_CCS_CentersOfExcellence coe
    ON coe.coe_id = p.COE_ID

INNER JOIN (   -- one row per CommentId (see header note 5)
    SELECT x.*,
        MAX(ISNULL(x.IsSubmitted, 0)) OVER (PARTITION BY x.CommentId) AS IsSubmittedAnyCopy,
        COUNT(*) OVER (PARTITION BY x.CommentId) AS CopiesOfComment,
        ROW_NUMBER() OVER (PARTITION BY x.CommentId ORDER BY x.UpdatedDate DESC, x.Id DESC) AS CopyRank
    FROM dbo.Basecamp_MessageBoards_MessageComments x
    WHERE x.CommentId IS NOT NULL
) mc
    ON TRY_CAST(mc.MessageId AS bigint) = TRY_CAST(pd.MessageBoardID AS bigint)
    AND mc.CopyRank = 1

WHERE
    (
        pd.StepName LIKE 'Stress Test 0%'
        OR pd.StepName LIKE 'Stress Test 1%'
        OR pd.StepName LIKE 'Stress Test 2%'
        OR pd.StepName LIKE 'Stress Test 3%'
        OR pd.StepName LIKE 'Stress Test 4%'
        OR pd.StepName LIKE 'Stress Test 5%'
    )
    /*BCP_ID_FILTER*/  -- optional project filter, filled with ? placeholders by app.db.queries.with_bcp_id_filter

ORDER BY
    pd.StepName,
    mc.MessageId,
    mc.CreatedDate,
    mc.CommentId;
