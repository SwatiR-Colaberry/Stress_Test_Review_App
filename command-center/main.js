import { loadRealData, computeFreshness } from "./data.js";
import { buildSampleData } from "./sample-data.js";
import { renderChrome } from "./chrome.js";
import { parseHash, onRouteChange, navigate } from "./router.js";
import { renderOverview } from "./tabs/overview.js";
import { renderPlaceholder } from "./tabs/placeholder.js";

const TABS = [
  { id: "overview", label: "Overview" },
  {
    id: "outcomes",
    label: "Outcomes",
    blurb:
      "The numbers this project has to move — drawn from plan.derived.measures. On real data, every measure reads “not measured yet” until the running system reports a figure; this project's files never carry the actual value, only the target.",
  },
  {
    id: "users",
    label: "Users & use case",
    blurb:
      "Who this is for and what they're trying to get done, taken from the roles your stories are written for (plan.derived.roles) and each story's narrative sentence.",
  },
  {
    id: "guardrails",
    label: "Guardrails",
    blurb:
      "The SAFE requirements this project promises never to violate (plan.derived.guardrails), and whether the stories that fulfil each one are actually verified yet.",
  },
  {
    id: "systems",
    label: "Systems",
    blurb:
      "Every system this project is meant to connect to (plan.derived.systems), each with a live indicator. None of them can be shown as connected from a static page — every indicator starts grey.",
  },
  {
    id: "project-management",
    label: "Project management",
    blurb:
      "A Gantt view of your releases and every task's due date, including how far a due date has slipped from when it was first given.",
  },
  {
    id: "agents",
    label: "AI agents",
    blurb:
      "Who owns each story today (plan.stories[].owner_agent) — owners, not a scoped AI agent roster. This project's plan doesn't carry agent definitions yet.",
  },
  {
    id: "knowledge-base",
    label: "Knowledge base",
    blurb:
      "Requirements-to-stories traceability, plus a chat panel that answers questions about this project's own data and cites where the answer came from.",
  },
  {
    id: "data-model",
    label: "Data model",
    blurb: "The tables behind this project's requirements, with fields and relationships, derived from the requirements themselves.",
  },
];

const state = {
  mode: localStorage.getItem("ccMode") === "sample" ? "sample" : "real",
  real: null,
  sample: null,
  error: null,
};

async function init() {
  try {
    state.real = await loadRealData();
    state.sample = buildSampleData(state.real.plan);
  } catch (err) {
    state.error = err;
  }
  render();
  onRouteChange(render);
}

function setMode(mode) {
  state.mode = mode;
  localStorage.setItem("ccMode", mode);
  render();
}

function render() {
  const root = document.getElementById("app");

  if (state.error) {
    root.innerHTML = `<div class="empty-state" style="margin:40px auto;max-width:560px;">
      <h2>Could not load project data</h2>
      <p>${state.error.message}</p>
      <p>This page reads <code>.colaberry/plan.json</code>, <code>.colaberry/progress.json</code> and <code>.colaberry/manifest.json</code> at runtime — confirm they're committed and this page is served from the repo root.</p>
    </div>`;
    return;
  }

  const dataset = state.mode === "sample" ? state.sample : state.real;
  const freshness = computeFreshness(dataset.manifest.generated_at);
  const { tabId, detail } = parseHash();
  const activeTabId = TABS.some((t) => t.id === tabId) ? tabId : "overview";
  if (!tabId) {
    navigate(`/overview`);
    return;
  }

  const content = renderChrome(root, {
    tabs: TABS,
    activeTabId,
    mode: state.mode,
    onModeChange: setMode,
    projectName: dataset.plan.project?.name || dataset.plan.project_name,
    repoName: dataset.plan.project?.repo_url?.replace(/^https?:\/\//, ""),
    freshness,
  });

  const ctx = { ...dataset, mode: state.mode };

  if (activeTabId === "overview") {
    renderOverview(content, ctx, detail.length ? detail : null);
    return;
  }

  const tabDef = TABS.find((t) => t.id === activeTabId);
  renderPlaceholder(content, { tabId: activeTabId, label: tabDef.label, blurb: tabDef.blurb }, detail.length ? detail : null);
}

init();
