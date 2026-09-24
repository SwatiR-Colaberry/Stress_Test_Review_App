import { loadRealData, computeFreshness } from "./data.js";
import { buildSampleData } from "./sample-data.js";
import { renderChrome } from "./chrome.js";
import { parseHash, onRouteChange, navigate } from "./router.js";
import { renderOverview } from "./tabs/overview.js";
import { renderOutcomes } from "./tabs/outcomes.js";
import { renderUsers } from "./tabs/users.js";
import { renderGuardrails } from "./tabs/guardrails.js";
import { renderSystems } from "./tabs/systems.js";
import { renderProjectManagement } from "./tabs/project-management.js";
import { renderAgents } from "./tabs/agents.js";
import { renderKnowledgeBase } from "./tabs/knowledge-base.js";
import { renderDataModel } from "./tabs/data-model.js";

const TABS = [
  { id: "overview", label: "Overview", render: renderOverview },
  { id: "outcomes", label: "Outcomes", render: renderOutcomes },
  { id: "users", label: "Users & use case", render: renderUsers },
  { id: "guardrails", label: "Guardrails", render: renderGuardrails },
  { id: "systems", label: "Systems", render: renderSystems },
  { id: "project-management", label: "Project management", render: renderProjectManagement },
  { id: "agents", label: "AI agents", render: renderAgents },
  { id: "knowledge-base", label: "Knowledge base", render: renderKnowledgeBase },
  { id: "data-model", label: "Data model", render: renderDataModel },
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
  const tabDef = TABS.find((t) => t.id === activeTabId);
  tabDef.render(content, ctx, detail.length ? detail : null);
}

init();
