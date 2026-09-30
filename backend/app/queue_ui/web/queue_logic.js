// Pure helpers for the Review Queue page (STORY-012): no DOM, no network, so
// they can be tested with Node (backend/app/queue_ui/test_web_logic.py).
"use strict";

const STATUSES = ["Pending", "In Review", "Feedback Generated", "Completed"];

// What each status means, shown in the "What each status means" section. The
// server works the status out the same way (backend/app/queue_ui/models.py).
const STATUS_MEANINGS = {
  "Pending": "A student asked for a review (##Critique##) and the AI draft is ready or on its way. No reviewer has made a decision yet.",
  "In Review": "A reviewer has approved, edited, rejected or added at least one finding. Nothing has been sent to the student.",
  "Feedback Generated": "Every finding has a decision and the reviewer prepared the final feedback. It is locked and waits to be posted to Basecamp.",
  "Completed": "Basecamp confirmed the feedback was posted on the student's thread. The review is finished and read-only.",
};

// Rows with the chosen status ("" or "All" = every row), order kept.
function filterRows(rows, status) {
  if (!status || status === "All") return rows.slice();
  return rows.filter((row) => row.status === status);
}

// {"All": n, "Pending": n, ...} for the filter buttons; every status present.
function countByStatus(rows) {
  const counts = { All: rows.length };
  STATUSES.forEach((s) => { counts[s] = 0; });
  rows.forEach((row) => { counts[row.status] = (counts[row.status] || 0) + 1; });
  return counts;
}

// A reviewer can still work on anything not Completed; the link opens the
// STORY-005 reviewer page. Completed reviews are read-only history.
function canReview(status) {
  return status !== "Completed";
}

// What the page says when a request fails. status 0 = no answer at all.
function explainFailure(status, data, timedOut) {
  const detail = (data && data.detail) || {};
  if (status === 0) {
    return timedOut ? "The server did not answer in time. Retry."
                    : "Could not reach the server (network problem). Retry.";
  }
  if (detail.reason_code === "MISSING_REVIEWER_IDENTITY") return "Enter your reviewer id above to open the queue.";
  if (detail.reason_code === "AI_CANNOT_REVIEW") return "That id is an AI/system identity; enter your own reviewer id.";
  if (detail.reason_code === "REVIEW_NOT_FOUND") {
    return "This review is not in the Review Queue (the server may have restarted). Choose one from the list.";
  }
  if (detail.reason_code === "REVIEW_STATE_MISMATCH") {
    return "This review's saved decisions do not match its newest AI draft (it was re-evaluated with newer rules). " +
      "Nothing was changed. Ask the developer to look at it.";
  }
  if (status === 503) return "Could not load: storage or the audit trail is unavailable. Retry; it is safe.";
  return `Unexpected answer from the server (${status}).`;
}

// Rows whose student name or review id contains the text (any case).
function searchRows(rows, text) {
  const needle = (text || "").trim().toLowerCase();
  if (!needle) return rows.slice();
  return rows.filter((row) => `${row.student_name || ""} ${row.review_id}`.toLowerCase().includes(needle));
}

// Position of a status in the review's life, 0..3, for the progress steps.
function stageIndex(status) {
  return STATUSES.indexOf(status);
}

// "just now", "5 min ago", "3 h ago", "2 days ago"; a future time (clock skew) is "just now".
function relativeTime(iso, nowMs) {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const minutes = Math.floor((nowMs - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "1 day ago" : `${days} days ago`;
}

// Only failures that may pass on their own get a Retry button.
function isRetryable(status) {
  return status === 0 || status === 503;
}

if (typeof module !== "undefined") {
  module.exports = { STATUSES, STATUS_MEANINGS, filterRows, searchRows, stageIndex, relativeTime, countByStatus, canReview, explainFailure, isRetryable };
}
