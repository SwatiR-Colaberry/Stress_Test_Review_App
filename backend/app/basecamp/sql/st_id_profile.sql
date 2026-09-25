-- ID profile for the ST0-ST5 history queries: COUNTS ONLY, no row values.
-- Answers: are the text MessageId / MessageBoardID columns numeric, is
-- CommentId unique and present, and is each message board used by exactly
-- one Stress Test step (otherwise a comment would be attributed to several
-- Stress Tests)? Read-only. See directives/ST-historical-comment-extraction.md.
--
-- Column types (check_db_connection.py, 2026-09-25):
--   mc.MessageId nvarchar(max), pd.MessageBoardID varchar(max),
--   sc.MessageId bigint, mc.CommentId bigint.
-- All comparisons are numeric (TRY_CAST), matching the history queries; text
-- comparison of these (max) columns across all projects exceeded the 120 s
-- query timeout. TRY_CAST('' AS bigint) returns 0, so blanks are removed
-- (NULLIF) before casting and counted separately. No IsActive filter.

WITH st_steps AS (
    SELECT
        pd.ID,
        SUBSTRING(pd.StepName, 13, 1) AS StressTest,
        pd.MessageBoardID,
        NULLIF(LTRIM(RTRIM(pd.MessageBoardID)), '') AS board_trimmed,
        TRY_CAST(NULLIF(LTRIM(RTRIM(pd.MessageBoardID)), '') AS bigint) AS board_num
    FROM dbo.ADF_CCS_BasecampProjects p
    INNER JOIN dbo.ADF_CCS_BasecampProjects_Details pd
        ON p.BCP_ID = pd.BCP_ID
    WHERE
        pd.StepName LIKE 'Stress Test 0%'
        OR pd.StepName LIKE 'Stress Test 1%'
        OR pd.StepName LIKE 'Stress Test 2%'
        OR pd.StepName LIKE 'Stress Test 3%'
        OR pd.StepName LIKE 'Stress Test 4%'
        OR pd.StepName LIKE 'Stress Test 5%'
),
boards AS (   -- one row per numeric message board used by ST steps
    SELECT board_num, COUNT(*) AS steps, COUNT(DISTINCT StressTest) AS stress_tests
    FROM st_steps
    WHERE board_num IS NOT NULL
    GROUP BY board_num
),
mc_all AS (
    SELECT
        mc.CommentId,
        mc.MessageId,
        NULLIF(LTRIM(RTRIM(mc.MessageId)), '') AS msg_trimmed,
        TRY_CAST(NULLIF(LTRIM(RTRIM(mc.MessageId)), '') AS bigint) AS msg_num
    FROM dbo.Basecamp_MessageBoards_MessageComments mc
),
st_comments AS (
    SELECT c.CommentId, b.steps, b.stress_tests
    FROM mc_all c
    INNER JOIN boards b ON b.board_num = c.msg_num
),
sc_threads AS (
    SELECT sc.MessageId, COUNT(*) AS assignments
    FROM dbo.ADF_BasecampStressTestCritiquer sc
    GROUP BY sc.MessageId
)
SELECT metric, value FROM (
              SELECT 10 AS ord, 'steps_total' AS metric, COUNT_BIG(*) AS value FROM st_steps
    UNION ALL SELECT 11, 'steps_board_null', COUNT_BIG(*) FROM st_steps WHERE MessageBoardID IS NULL
    UNION ALL SELECT 12, 'steps_board_blank', COUNT_BIG(*) FROM st_steps WHERE MessageBoardID IS NOT NULL AND board_trimmed IS NULL
    UNION ALL SELECT 13, 'steps_board_numeric', COUNT_BIG(*) FROM st_steps WHERE board_num IS NOT NULL
    UNION ALL SELECT 14, 'steps_board_other_text', COUNT_BIG(*) FROM st_steps WHERE board_trimmed IS NOT NULL AND board_num IS NULL
    UNION ALL SELECT 15, 'boards_distinct', COUNT_BIG(*) FROM boards
    UNION ALL SELECT 16, 'boards_used_by_more_than_one_step', COUNT_BIG(*) FROM boards WHERE steps > 1
    UNION ALL SELECT 17, 'boards_used_by_more_than_one_stress_test', COUNT_BIG(*) FROM boards WHERE stress_tests > 1

    UNION ALL SELECT 20, 'comments_table_total', COUNT_BIG(*) FROM mc_all
    UNION ALL SELECT 21, 'comments_table_msgid_null', COUNT_BIG(*) FROM mc_all WHERE MessageId IS NULL
    UNION ALL SELECT 22, 'comments_table_msgid_blank', COUNT_BIG(*) FROM mc_all WHERE MessageId IS NOT NULL AND msg_trimmed IS NULL
    UNION ALL SELECT 23, 'comments_table_msgid_numeric', COUNT_BIG(*) FROM mc_all WHERE msg_num IS NOT NULL
    UNION ALL SELECT 24, 'comments_table_msgid_other_text', COUNT_BIG(*) FROM mc_all WHERE msg_trimmed IS NOT NULL AND msg_num IS NULL

    UNION ALL SELECT 30, 'st_comments_distinct', COUNT_BIG(*) FROM st_comments
    UNION ALL SELECT 31, 'st_comments_on_boards_shared_by_steps', COUNT_BIG(*) FROM st_comments WHERE steps > 1
    UNION ALL SELECT 32, 'st_comments_on_boards_shared_by_stress_tests', COUNT_BIG(*) FROM st_comments WHERE stress_tests > 1
    UNION ALL SELECT 33, 'st_comments_commentid_null', COUNT_BIG(*) FROM st_comments WHERE CommentId IS NULL
    UNION ALL SELECT 34, 'st_commentid_values_duplicated', COUNT_BIG(*) FROM (
                  SELECT CommentId FROM st_comments WHERE CommentId IS NOT NULL
                  GROUP BY CommentId HAVING COUNT(*) > 1) d

    UNION ALL SELECT 40, 'critiquer_rows_total', COUNT_BIG(*) FROM dbo.ADF_BasecampStressTestCritiquer
    UNION ALL SELECT 41, 'critiquer_threads_multiple_assignments', COUNT_BIG(*) FROM sc_threads WHERE assignments > 1
    UNION ALL SELECT 42, 'critiquer_threads_matching_st_boards', COUNT_BIG(*) FROM sc_threads t
              WHERE EXISTS (SELECT 1 FROM boards b WHERE b.board_num = t.MessageId)
) m
ORDER BY ord;
