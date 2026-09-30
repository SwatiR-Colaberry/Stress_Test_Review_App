// Rules page (STORY-012). Reads GET /rules-ui/modules (audited on the
// server as rules_viewed, with the reviewer id and time) and shows one tab per
// Stress Test. A link like /rules/#ST0-002 opens that rule's tab and scrolls
// to it (used by the reviewer page's "What does this rule mean?").
//
// Failure handling: the request has a timeout; a failure shows a banner with
// Retry where it may help. A Stress Test whose rule file cannot be read is
// shown as "not available" with its reason, without hiding the others.
"use strict";

const TIMEOUT_MS = 15000;
const $ = (id) => document.getElementById(id);
let modules = [];
let current = null; // stress_test_id of the open tab

const REASONS = {
  MISSING_REVIEWER_IDENTITY: "Enter your reviewer id above to see the rules.",
  AI_CANNOT_REVIEW: "That id is an AI/system identity; enter your own reviewer id.",
  RULE_REGISTRY_UNREADABLE: "The list of Stress Test rules could not be read. Retry; if it keeps failing, tell the developer.",
};
const MODULE_REASONS = {
  RULE_MODULE_NOT_FOUND: "The rule file for this Stress Test is missing.",
  RULE_MODULE_INVALID: "The rule file for this Stress Test is not valid, so it is not shown.",
  RULE_VERSION_MISMATCH: "The rule file names a different Stress Test or version than the registry.",
};

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "text") node.textContent = value; // never innerHTML
    else if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  children.flat().forEach((child) => child && node.append(child));
  return node;
}

function storage(action, value) {
  try {
    if (action === "get") return localStorage.getItem("reviewer-id") || "";
    localStorage.setItem("reviewer-id", value);
  } catch (err) {
    console.warn("reviewer id not remembered:", err.name);
  }
  return "";
}

function showBanner(message, onRetry) {
  $("banner").hidden = false;
  $("banner-text").textContent = message;
  $("banner-retry").hidden = !onRetry;
  $("banner-retry").onclick = onRetry;
}

async function load() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let status = 0;
  let data = null;
  try {
    const response = await fetch("/rules-ui/modules", {
      signal: controller.signal, headers: { "X-Reviewer-Id": $("reviewer-id").value.trim() } });
    status = response.status;
    data = await response.json().catch(() => null);
  } catch (err) {
    showBanner(err.name === "AbortError" ? "The server did not answer in time. Retry." :
      "Could not reach the server (network problem). Retry.", load);
    return;
  } finally {
    clearTimeout(timer);
  }
  if (status !== 200) {
    const reason = data && data.detail && data.detail.reason_code;
    modules = [];
    render();
    showBanner(REASONS[reason] || `Unexpected answer from the server (${status}).`,
               status === 503 ? load : null);
    return;
  }
  $("banner").hidden = true;
  modules = data.modules;
  const wanted = stressTestOfRule(location.hash.slice(1));
  current = (modules.find((m) => m.stress_test_id === wanted) || modules[0] || {}).stress_test_id || null;
  render();
  if (wanted) document.getElementById(location.hash.slice(1))?.scrollIntoView();
}

function render() {
  $("tabs").replaceChildren(...modules.map((m) => el("button", {
    type: "button", role: "tab", "aria-selected": String(m.stress_test_id === current),
    text: `${m.name}${m.available ? "" : " (not available)"}`,
    onclick: () => { current = m.stress_test_id; render(); },
  })));
  const module = modules.find((m) => m.stress_test_id === current);
  if (!module) {
    $("module").replaceChildren(modules.length ? "" : el("p", { class: "empty", text: "No Stress Test rules to show." }));
    return;
  }
  if (!module.available) {
    $("module").replaceChildren(el("div", { class: "card" },
      el("h2", { text: module.name }),
      el("p", { class: "status bad", text: MODULE_REASONS[module.reason_code] || module.reason_code })));
    return;
  }
  const search = $("search").value;
  const stages = module.stages.map((stage) => stageSection(stage, stage.rules.filter((r) => ruleMatches(r, search))))
    .filter(Boolean);
  $("module").replaceChildren(
    overview(module),
    ...(stages.length ? stages : [el("p", { class: "empty", text: "No rule matches your search." })]),
    notesSection(module),
  );
}

function overview(m) {
  const count = m.problem_count ? `${m.problem_count.min}–${m.problem_count.max} problems` : null;
  return el("section", { class: "overview" },
    el("div", { class: "card" },
      el("h2", { text: `${m.name} · rules ${m.version}` }),
      el("p", { text: m.purpose }),
      m.required_problem_fields.length ? el("div", {},
        el("h3", { text: `Every problem needs${count ? ` (${count})` : ""}` }),
        el("div", { class: "chips" }, m.required_problem_fields.map((f) => el("span", { class: "chip", text: f })))) : null),
    el("div", { class: "card" },
      el("h3", { text: "Not checked in this Stress Test" }),
      el("ul", {}, m.out_of_scope.map((item) => el("li", { text: item }))),
      m.tolerance.length ? el("details", {}, el("summary", { text: "What wording differences are allowed" }),
        el("ul", {}, m.tolerance.map((item) => el("li", { text: item })))) : null),
  );
}

// A stage whose rules all miss the search is hidden. A stage with no rules at
// all (e.g. ST0's advisory stage) is guidance only: shown unless searching.
function stageSection(stage, rules) {
  const guidanceOnly = !stage.rules.length && stage.instructions.length && !$("search").value.trim();
  if (!rules.length && !guidanceOnly) return null;
  return el("section", { class: "stage" },
    el("div", { class: "stage-head" },
      el("h2", { text: `Stage ${stage.number} · ${stage.name}` }),
      el("span", { class: `tag ${stage.blocking ? "blocking" : "nonblocking"}`,
                   text: stage.blocking ? "Blocking: later stages wait until this passes" : "Not blocking" })),
    stage.instructions.length ? el("p", { class: "stage-note", text: stage.instructions.join(" ") }) : null,
    el("div", { class: "rules" }, rules.map(ruleCard)));
}

function ruleCard(rule) {
  const ex = rule.example;
  return el("article", { class: "card rule", id: rule.id },
    el("div", { class: "head" },
      el("a", { class: "rule-id", href: `#${rule.id}`, text: rule.id }),
      el("h3", { text: rule.check }),
      el("span", { class: "tag", text: rule.default_severity })),
    el("p", { class: "feedback" }, el("b", { text: "What the student is told if it fails" }), rule.failure_feedback),
    ex ? el("div", { class: "examples" },
      el("div", { class: "example pass" }, el("b", { text: "✓ Passes, for example" }), ex.passes),
      el("div", { class: "example fail" }, el("b", { text: "✗ Fails, for example" }), ex.fails))
      : el("p", { class: "sub", text: "No example yet." }),
    rule.evaluation_notes.length ? el("details", {}, el("summary", { text: "How reviewers apply this rule" }),
      el("ul", { class: "notes" }, rule.evaluation_notes.map((n) => el("li", { text: n })))) : null,
  );
}

function notesSection(m) {
  if (!m.reviewer_notes.length && !m.advisory_guidance.length) return null;
  return el("section", { class: "card stage" },
    el("h2", { text: "Notes for reviewers (never a rule failure)" }),
    el("ul", { class: "notes" },
      m.reviewer_notes.map((n) => el("li", {}, el("b", { text: `${n.when} ` }), n.note)),
      m.advisory_guidance.map((g) => el("li", { text: g }))));
}

// ---- wiring ----------------------------------------------------------------

$("reviewer-id").value = storage("get");
$("reviewer-id").addEventListener("input", () => storage("set", $("reviewer-id").value.trim()));
$("reviewer-id").addEventListener("change", load);
$("search").addEventListener("input", render);
window.addEventListener("hashchange", () => {
  const wanted = stressTestOfRule(location.hash.slice(1));
  if (wanted && wanted !== current) { current = wanted; render(); document.getElementById(location.hash.slice(1))?.scrollIntoView(); }
});
window.addEventListener("pageshow", (e) => { if (e.persisted) { $("reviewer-id").value = storage("get"); load(); } });
load();
