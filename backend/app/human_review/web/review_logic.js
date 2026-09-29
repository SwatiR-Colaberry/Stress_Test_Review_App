// Pure helpers for the reviewer page (STORY-005): no DOM, no network, so they
// can be tested with Node (backend/app/human_review/test_web_logic.py).
"use strict";

// The "Add finding" request. If the last add failed with the same text, it is
// sent again with the SAME action_id, so a request that did reach the server
// (e.g. the answer timed out) is applied once, not twice. Text is trimmed here,
// as the server trims it, so a trailing newline cannot make it look different.
function addFindingAction(failed, rawText, ruleId, newActionId) {
  const text = rawText.trim();
  if (failed && failed.action && failed.action.text === text) return failed.action;
  const rule = (ruleId || "").trim();
  return { action_id: newActionId(), kind: "add_finding", text, ...(rule ? { rule_id: rule } : {}) };
}

if (typeof module !== "undefined") module.exports = { addFindingAction };
