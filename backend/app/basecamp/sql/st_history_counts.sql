-- Sizing query: how many ST0-ST5 projects, message threads and comments the
-- full extraction (st_history_comments.sql) will return. Run this FIRST.
-- Read-only. See directives/ST-historical-comment-extraction.md.
-- Changes from the query as provided (2026-09-25, see the directive):
--   - no IsActive filter: no project has IsActive = 1 (NULL or 0 only), and
--     proc_AllStressTestData does not filter on it either (user-confirmed).
--   - MessageId joined as numbers: the columns are nvarchar/varchar/bigint
--     across tables; every value was profiled as numeric (st_id_profile.sql).

SELECT
    LEFT(pd.StepName, 13) AS StressTest,
    COUNT(DISTINCT p.BCP_ID) AS Projects,
    COUNT(DISTINCT mc.MessageId) AS MessageThreads,
    COUNT(DISTINCT mc.CommentId) AS Comments
FROM dbo.ADF_CCS_BasecampProjects p
INNER JOIN dbo.ADF_CCS_BasecampProjects_Details pd
    ON p.BCP_ID = pd.BCP_ID
LEFT JOIN dbo.Basecamp_MessageBoards_MessageComments mc
    ON TRY_CAST(mc.MessageId AS bigint) = TRY_CAST(pd.MessageBoardID AS bigint)
WHERE
    (
        pd.StepName LIKE 'Stress Test 0%'
        OR pd.StepName LIKE 'Stress Test 1%'
        OR pd.StepName LIKE 'Stress Test 2%'
        OR pd.StepName LIKE 'Stress Test 3%'
        OR pd.StepName LIKE 'Stress Test 4%'
        OR pd.StepName LIKE 'Stress Test 5%'
    )
GROUP BY LEFT(pd.StepName, 13)
ORDER BY StressTest;
