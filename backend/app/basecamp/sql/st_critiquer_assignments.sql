-- Critiquer assignment history for every ST0-ST5 message thread: one row per
-- assignment record, NOT per comment. Matched to comments in Python by
-- MessageId and time (the critiquer assigned at or before the comment), so a
-- reassignment never duplicates comment rows. Read-only.
-- Scope matches st_history_comments.sql (all projects, ST0-ST5 steps).
-- pd.MessageBoardID is varchar, sc.MessageId is bigint: compared as numbers
-- via TRY_CAST so one bad value can never fail the whole query.
-- See directives/ST-historical-comment-extraction.md.

SELECT
    sc.BasecampStressTestCritiquerId,
    sc.MessageId,
    sc.Critiquer,
    sc.CreatedDate AS CritiquerAssignedDate
FROM dbo.ADF_BasecampStressTestCritiquer sc
WHERE EXISTS (
    SELECT 1
    FROM dbo.ADF_CCS_BasecampProjects p
    INNER JOIN dbo.ADF_CCS_BasecampProjects_Details pd
        ON p.BCP_ID = pd.BCP_ID
    WHERE TRY_CAST(pd.MessageBoardID AS bigint) = sc.MessageId
      AND (
          pd.StepName LIKE 'Stress Test 0%'
          OR pd.StepName LIKE 'Stress Test 1%'
          OR pd.StepName LIKE 'Stress Test 2%'
          OR pd.StepName LIKE 'Stress Test 3%'
          OR pd.StepName LIKE 'Stress Test 4%'
          OR pd.StepName LIKE 'Stress Test 5%'
      )
      /*BCP_ID_FILTER*/  -- optional project filter, filled with ? placeholders by app.db.queries.with_bcp_id_filter
)
ORDER BY
    sc.MessageId,
    sc.CreatedDate,
    sc.BasecampStressTestCritiquerId;
