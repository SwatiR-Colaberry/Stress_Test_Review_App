// Overview — the 30-second screen. Headline counts come straight out of
// progress.totals (never recomputed by looping stories, per DATA_CONTRACT.md
// and STORY-000's own instruction) so the page and the file can never
// disagree with each other.

import { renderCrumb, sampleTag } from "../chrome.js";
import { navigate } from "../router.js";
import { joinStories, formatDate } from "../data.js";

function releasePosition(schedule, releases, now) {
  const today = now.toISOString().slice(0, 10);
  const current = releases.find((r) => r.starts_on && r.ends_on && today >= r.starts_on && today <= r.ends_on);
  if (current) return { kind: "in-release", release: current };

  const upcoming = releases
    .filter((r) => r.starts_on && r.starts_on > today)
    .sort((a, b) => a.starts_on.localeCompare(b.starts_on))[0];
  if (upcoming) return { kind: "before-release", release: upcoming };

  if (schedule.build_end && today > schedule.build_end) return { kind: "after-build" };
  return { kind: "unknown" };
}

export function renderOverview(container, ctx, detail) {
  const { plan, progress, mode } = ctx;
  const totals = progress.totals || {};

  if (detail) {
    renderDetail(container, ctx, detail);
    return;
  }

  const h1 = document.createElement("h1");
  h1.className = "tab-title";
  h1.textContent = plan.project?.name || plan.project_name || "Command Center";
  container.appendChild(h1);

  const p = document.createElement("p");
  p.className = "tab-desc";
  p.textContent = plan.project?.descriptor || plan.descriptor || "";
  container.appendChild(p);

  const pos = releasePosition(plan.schedule || {}, plan.releases || [], new Date());
  let whereText = "Schedule position not available yet.";
  if (pos.kind === "in-release") whereText = `In ${pos.release.key} · ${pos.release.name} (ends ${formatDate(pos.release.ends_on)})`;
  else if (pos.kind === "before-release") whereText = `Ahead of ${pos.release.key} · ${pos.release.name} (starts ${formatDate(pos.release.starts_on)})`;
  else if (pos.kind === "after-build") whereText = "Past build end — demo prep window";

  const grid = document.createElement("div");
  grid.className = "card-grid";

  grid.appendChild(
    makeCard("What this is", plan.project?.name || "—", "Project name & descriptor", () => navigate("/overview/what-this-is"), mode)
  );
  grid.appendChild(
    makeCard("Where you are", whereText, `Build: ${formatDate(plan.schedule?.build_start)} → ${formatDate(plan.schedule?.build_end)} · Demo ${formatDate(plan.schedule?.demo_day)}`, () => navigate("/overview/schedule"), mode)
  );
  grid.appendChild(
    makeCard("Stories", `${totals.stories_verified ?? 0} / ${totals.stories_total ?? 0}`, "verified of total", () => navigate("/overview/stories"), mode)
  );
  grid.appendChild(
    makeCard("Criteria", `${totals.criteria_passed ?? 0} / ${totals.criteria_total ?? 0}`, "acceptance criteria passed", () => navigate("/overview/criteria"), mode)
  );
  grid.appendChild(
    makeCard("Points", `${totals.points_awarded ?? 0}`, "points, from progress.totals", () => navigate("/overview/points"), mode)
  );

  container.appendChild(grid);
}

function makeCard(label, value, sub, onClick, mode) {
  const card = document.createElement("button");
  card.className = "card";
  card.innerHTML = `<span class="card-label">${label}</span><span class="card-value">${value}</span><span class="card-sub">${sub}</span>`;
  if (mode === "sample") card.appendChild(sampleTag());
  card.onclick = onClick;
  return card;
}

function renderDetail(container, ctx, detail) {
  const { plan, progress } = ctx;
  const which = detail[0];
  renderCrumb(container, { label: which, onBack: () => navigate("/overview") });

  if (which === "what-this-is") {
    const h2 = document.createElement("h2");
    h2.textContent = plan.project?.name;
    const desc = document.createElement("p");
    desc.textContent = plan.project?.descriptor;
    const meta = document.createElement("p");
    meta.className = "tab-desc";
    meta.innerHTML = plan.project?.repo_url
      ? `Repo: <a href="${plan.project.repo_url}" target="_blank" rel="noopener">${plan.project.repo_url}</a>`
      : "No repo URL on file.";
    container.append(h2, desc, meta);
    return;
  }

  if (which === "schedule") {
    const sched = plan.schedule || {};
    const list = document.createElement("ul");
    list.className = "list-plain";
    list.innerHTML = `
      <li>Build start: ${formatDate(sched.build_start)}</li>
      <li>Build end: ${formatDate(sched.build_end)}</li>
      <li>Demo day: ${formatDate(sched.demo_day)}</li>
      <li>Demo release: ${sched.demo_release_key}</li>
      <li>Roadmap releases (after demo): ${(sched.roadmap_release_keys || []).join(", ")}</li>
    `;
    container.appendChild(list);
    if ((sched.prep || []).length) {
      const h2 = document.createElement("h2");
      h2.textContent = "Demo prep tasks";
      container.appendChild(h2);
      const prepList = document.createElement("ul");
      prepList.className = "list-plain";
      prepList.innerHTML = sched.prep
        .map((t) => `<li>${t.key} — ${t.title} (due ${formatDate(t.due_on)})</li>`)
        .join("");
      container.appendChild(prepList);
    }
    return;
  }

  const stories = joinStories(plan, progress);

  if (which === "stories") {
    container.appendChild(storiesTable(stories, ["id", "title", "release", "state"]));
    return;
  }

  if (which === "criteria") {
    container.appendChild(storiesTable(stories, ["id", "title", "criteria"]));
    return;
  }

  if (which === "points") {
    container.appendChild(storiesTable(stories, ["id", "title", "points"]));
    const note = document.createElement("p");
    note.className = "tab-desc";
    note.textContent = "Points come directly from progress.json's per-story verification.points_awarded — this file does not say what they convert to.";
    container.appendChild(note);
    return;
  }

  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.innerHTML = "<h2>Unknown detail</h2>";
  container.appendChild(empty);
}

function storiesTable(stories, columns) {
  const table = document.createElement("table");
  table.className = "data-table";
  const headers = {
    id: "Story",
    title: "Title",
    release: "Release",
    state: "State",
    criteria: "Criteria",
    points: "Points",
  };
  table.innerHTML = `<thead><tr>${columns.map((c) => `<th>${headers[c]}</th>`).join("")}</tr></thead>`;
  const tbody = document.createElement("tbody");
  stories.forEach((s) => {
    const tr = document.createElement("tr");
    tr.innerHTML = columns
      .map((c) => {
        if (c === "id") return `<td>${s.id}</td>`;
        if (c === "title") return `<td>${s.title}</td>`;
        if (c === "release") return `<td>${s.release || "—"}</td>`;
        if (c === "state") return `<td>${s.state}</td>`;
        if (c === "criteria") return `<td>${s.criteriaPassed} / ${s.criteriaTotal}</td>`;
        if (c === "points") return `<td>${s.pointsAwarded ?? "—"}</td>`;
        return "<td></td>";
      })
      .join("");
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  return table;
}
