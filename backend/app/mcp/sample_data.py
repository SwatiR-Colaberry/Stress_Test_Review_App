"""Sample Basecamp submission records for the MCP resource below.

SAMPLE DATA ONLY. There is no Basecamp API client in this repo yet
(REQ-004: retrieve submission data; REQ-012: Basecamp OAuth 2.0 — both
unbuilt, blocked on Master Spec Sec.27's Basecamp environment/credential
inputs). The shape here matches what Master Spec Sec.2/Sec.4 says a real
submission record must carry (project, student, Stress Test, MessageId,
CommentId, critique-marker state) so the resource is a faithful stand-in
for the real thing once it exists, not an arbitrary placeholder.
"""

SAMPLE_SUBMISSIONS = [
    {
        "project": "Retail Demand Forecasting",
        "student": "j.alvarez",
        "stress_test": "ST0",
        "message_id": "msg-10234",
        "comment_id": "cmt-58831",
        "critique_marker_detected": True,
        "submitted_at": "2026-09-14T18:02:00Z",
    },
    {
        "project": "Hospital Readmission Risk",
        "student": "t.nguyen",
        "stress_test": "ST0",
        "message_id": "msg-10240",
        "comment_id": "cmt-58902",
        "critique_marker_detected": False,
        "submitted_at": "2026-09-15T09:47:00Z",
    },
    {
        "project": "E-commerce Churn Prediction",
        "student": "s.patel",
        "stress_test": "ST0",
        "message_id": "msg-10251",
        "comment_id": "cmt-59015",
        "critique_marker_detected": True,
        "submitted_at": "2026-09-16T14:15:00Z",
    },
]
