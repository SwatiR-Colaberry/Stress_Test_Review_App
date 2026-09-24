// Users and use case — who this is for, taken from plan.derived.roles and
// the "As a <role>, I want ..." sentence each story was written from.

import { renderCrumb, sampleTag, stateTagHtml } from "../chrome.js";
import { navigate } from "../router.js";

function storiesForRole(stories, role) {
  const needle = `as a ${role}`.toLowerCase();
  return stories.filter((s) => (s.narrative || "").toLowerCase().startsWith(needle));
}

export function renderUsers(container, ctx, detail) {
  const { plan, progress, mode } = ctx;
  const roles = plan.derived?.roles || [];
  const progById = new Map((progress.stories || []).map((s) => [s.id, s]));

  const h1 = document.createElement("h1");
  h1.className = "tab-title";
  h1.textContent = "Users & use case";
  const p = document.createElement("p");
  p.className = "tab-desc";
  p.textContent = "The roles your stories are written for, and what each one is trying to get done.";
  container.append(h1, p);

  if (detail) {
    renderRoleDetail(container, ctx, decodeURIComponent(detail[0]));
    return;
  }

  if (roles.length === 0) {
    container.innerHTML += `<div class="empty-state"><h2>No roles found</h2><p>plan.derived.roles is empty.</p></div>`;
    return;
  }

  const grid = document.createElement("div");
  grid.className = "card-grid";
  roles.forEach((role) => {
    const owned = storiesForRole(plan.stories || [], role);
    const verifiedCount = owned.filter((s) => progById.get(s.id)?.verification?.state === "verified").length;
    const card = document.createElement("button");
    card.className = "card";
    card.innerHTML = `<span class="card-label">Role</span><span class="card-value" style="font-size:18px; text-transform:capitalize;">${role}</span><span class="card-sub">${owned.length} stor${owned.length === 1 ? "y" : "ies"} · ${verifiedCount} verified</span>`;
    if (mode === "sample") card.appendChild(sampleTag());
    card.onclick = () => navigate(`/users/${encodeURIComponent(role)}`);
    grid.appendChild(card);
  });
  container.appendChild(grid);
}

function renderRoleDetail(container, ctx, role) {
  const { plan, progress } = ctx;
  renderCrumb(container, { label: role, onBack: () => navigate("/users") });
  const progById = new Map((progress.stories || []).map((s) => [s.id, s]));
  const owned = storiesForRole(plan.stories || [], role);

  const h2 = document.createElement("h2");
  h2.style.textTransform = "capitalize";
  h2.textContent = role;
  container.appendChild(h2);

  if (owned.length === 0) {
    container.innerHTML += `<div class="empty-state"><h2>No stories for this role</h2></div>`;
    return;
  }

  const list = document.createElement("ul");
  list.className = "list-plain";
  list.innerHTML = owned
    .map((s) => {
      const state = progById.get(s.id)?.verification?.state ?? "not_started";
      return `<li><strong>${s.id}</strong> — ${s.narrative} ${stateTagHtml(state)}</li>`;
    })
    .join("");
  container.appendChild(list);
}
