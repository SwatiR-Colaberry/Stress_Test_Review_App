// Pure helpers for the signed-in bar on every reviewer page (STORY-014): no
// DOM, no network, so they can be tested with Node
// (backend/app/human_review/test_web_logic.py).
"use strict";

// Where to send someone whose session is missing or has ended. Only this
// page's own path and query go into "next" (the server checks it again).
function signInUrl(pathAndQuery, expired) {
  const next = typeof pathAndQuery === "string" && pathAndQuery.startsWith("/") ? pathAndQuery : "/queue/";
  return `/auth/signin?${expired ? "expired=1&" : ""}next=${encodeURIComponent(next)}`;
}

function roleLabel(role) {
  return role === "admin" ? "Admin" : role === "reviewer" ? "Reviewer" : "";
}

// Plain words for the sign-in related refusals every API can give, or null
// when the answer is about something else (each page explains those).
function explainAuthFailure(status, data) {
  const code = data && data.detail && data.detail.reason_code;
  if (status === 401 || code === "NOT_SIGNED_IN") return "Your session has ended. Sign in again to continue.";
  if (code === "ADMIN_ONLY") return "Only an admin can do this.";
  if (code === "ROLE_LIST_UNAVAILABLE") return "The reviewer list cannot be read right now. Try again later.";
  return null;
}

if (typeof module !== "undefined") module.exports = { signInUrl, roleLabel, explainAuthFailure };
