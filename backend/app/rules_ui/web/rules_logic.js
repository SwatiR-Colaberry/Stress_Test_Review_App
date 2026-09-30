// Pure helpers for the Rules page (STORY-012): no DOM, no network, so they
// can be tested with Node (backend/app/rules_ui/test_web_logic.py).
"use strict";

// Does the rule mention the search text anywhere a reviewer would look
// (id, check, feedback, notes, examples)? Empty text matches everything.
function ruleMatches(rule, text) {
  const needle = (text || "").trim().toLowerCase();
  if (!needle) return true;
  const example = rule.example || {};
  return [rule.id, rule.check, rule.failure_feedback, rule.default_severity, ...(rule.evaluation_notes || []),
          example.passes, example.fails].some((field) => (field || "").toLowerCase().includes(needle));
}

// "ST0-002" -> "ST0": which Stress Test tab a rule link (#ST0-002) opens.
function stressTestOfRule(ruleId) {
  const match = /^(ST\d+)-\d{3}$/.exec(ruleId || "");
  return match ? match[1] : null;
}

if (typeof module !== "undefined") module.exports = { ruleMatches, stressTestOfRule };
