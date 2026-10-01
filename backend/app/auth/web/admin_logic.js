// Pure helpers for the Admins page (STORY-014): no DOM, no network, so they
// can be tested with Node (backend/app/auth/test_web_logic.py).
"use strict";

const ROLE_REASONS = {
  BOOTSTRAP_ADMIN: "This admin is set in the server configuration and cannot be changed here.",
  LAST_ADMIN: "This is the last admin, so they cannot be removed or made a reviewer. Add another admin first.",
  INVALID_EMAIL: "That is not a valid email address.",
};

// What the page says when a role change fails. status 0 = no answer at all.
function explainRoleFailure(status, data, timedOut) {
  const detail = (data && data.detail) || {};
  if (status === 0) {
    return timedOut ? "The server did not answer in time. Nothing may have changed; reload to check."
                    : "Could not reach the server (network problem). Retry.";
  }
  if (ROLE_REASONS[detail.reason_code]) return ROLE_REASONS[detail.reason_code];
  if (status === 422) return "Enter a valid email address and choose a role.";
  if (status === 503) return "Nothing changed: the role list or the audit trail is unavailable. Retry; it is safe.";
  return `Unexpected answer from the server (${status}).`;
}

// The sentence shown after a change succeeds.
function describeChange(change) {
  const role = change.role === "admin" ? "an admin" : "a reviewer";
  switch (change.result) {
    case "added": return `${change.email} was added as ${role}.`;
    case "changed": return `${change.email} is now ${role}.`;
    case "unchanged": return `${change.email} was already ${role}; nothing changed.`;
    case "removed": return `${change.email} was removed and can no longer sign in.`;
    case "not_found": return `${change.email} was not on the list; nothing changed.`;
    default: return "Saved.";
  }
}

if (typeof module !== "undefined") module.exports = { explainRoleFailure, describeChange };
