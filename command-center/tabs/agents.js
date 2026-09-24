// AI agents — this project's plan.agents[] is empty, so there is no scoped
// agent roster yet. Built instead from who owns each story (owner_agent).
// These are owners, not agents, and the tab says so rather than presenting
// a job title as an AI agent.

import { renderCrumb, stateTagHtml } from "../chrome.js";
import { navigate } from "../router.js";

function groupByOwner(stories) {
  const map = new Map();
  stories.forEach((s) => {
    const key = s.owner_agent || "Unassigned";
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(s);
  });
  return map;
}

export function renderAgents(container, ctx, detail) {
  const { plan, progress } = ctx;
  const stories = plan.stories || [];
  const progById = new Map((progress.stories || []).map((s) => [s.id, s]));
  const agentsDefined = plan.agents || [];

  const h1 = document.createElement("h1");
  h1.className = "tab-title";
  h1.textContent = "AI agents";
  const p = document.createElement("p");
  p.className = "tab-desc";
  p.textContent = agentsDefined.length
    ? "The agents defined in this project's plan."
    : "This project's plan does not carry a scoped agent roster yet. What follows is who owns each story today — owners, not scoped AI agents.";
  container.append(h1, p);

  if (detail) {
    renderOwnerDetail(container, ctx, decodeURIComponent(detail[0]));
    return;
  }

  if (agentsDefined.length === 0) {
    const grouped = groupByOwner(stories);
    const grid = document.createElement("div");
    grid.className = "card-grid";
    for (const [owner, owned] of grouped.entries()) {
      const verifiedCount = owned.filter((s) => progById.get(s.id)?.verification?.state === "verified").length;
      const card = document.createElement("button");
      card.className = "card";
      card.innerHTML = `<span class="card-label">Owner</span><span class="card-value" style="font-size:18px;">${owner}</span><span class="card-sub">${owned.length} stor${owned.length === 1 ? "y" : "ies"} owned · ${verifiedCount} verified · no skills registered yet</span>`;
      card.onclick = () => navigate(`/agents/${encodeURIComponent(owner)}`);
      grid.appendChild(card);
    }
    container.appendChild(grid);
    return;
  }

  // Reserved for when plan.agents[] is populated — render real agent cards.
  const grid = document.createElement("div");
  grid.className = "card-grid";
  agentsDefined.forEach((a) => {
    const card = document.createElement("button");
    card.className = "card";
    card.innerHTML = `<span class="card-label">${a.trigger_type || "Agent"}</span><span class="card-value" style="font-size:16px;">${a.name}</span><span class="card-sub">${a.purpose || ""}</span>`;
    card.onclick = () => navigate(`/agents/${encodeURIComponent(a.id)}`);
    grid.appendChild(card);
  });
  container.appendChild(grid);
}

function renderOwnerDetail(container, ctx, owner) {
  const { plan, progress } = ctx;
  renderCrumb(container, { label: owner, onBack: () => navigate("/agents") });
  const progById = new Map((progress.stories || []).map((s) => [s.id, s]));
  const owned = (plan.stories || []).filter((s) => (s.owner_agent || "Unassigned") === owner);

  const h2 = document.createElement("h2");
  h2.textContent = owner;
  const note = document.createElement("p");
  note.className = "tab-desc";
  note.textContent = "This is a story owner, not a scoped AI agent. No runs have been recorded — there is no agent yet to run.";
  container.append(h2, note);

  const h3 = document.createElement("h2");
  h3.textContent = "Owns";
  container.appendChild(h3);
  const list = document.createElement("ul");
  list.className = "list-plain";
  list.innerHTML = owned
    .map((s) => `<li><strong>${s.id}</strong> — ${s.title} ${stateTagHtml(progById.get(s.id)?.verification?.state ?? "not_started")}</li>`)
    .join("");
  container.appendChild(list);

  const h4 = document.createElement("h2");
  h4.textContent = "Skills";
  const skillsP = document.createElement("p");
  skillsP.className = "tab-desc";
  skillsP.textContent = "No skills registered yet.";
  container.append(h4, skillsP);
}
