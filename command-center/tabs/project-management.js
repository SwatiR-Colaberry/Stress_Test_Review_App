// Project management — a Gantt-style view of releases, and every task
// (story) with its current due date next to the date it was FIRST given.
// The gap between the two is slippage; this project has none yet (every
// due_on still equals due_baseline_on), and that is shown plainly rather
// than hidden.

import { renderCrumb, stateTagHtml } from "../chrome.js";
import { navigate } from "../router.js";
import { joinStories, formatDate } from "../data.js";

const DAY_MS = 24 * 60 * 60 * 1000;
function toUtcDay(iso) {
  return new Date(`${iso}T00:00:00Z`).getTime();
}

export function renderProjectManagement(container, ctx, detail) {
  const { plan, progress } = ctx;

  const h1 = document.createElement("h1");
  h1.className = "tab-title";
  h1.textContent = "Project management";
  const p = document.createElement("p");
  p.className = "tab-desc";
  p.textContent = "Your releases and every task's due date, against the date it was first given.";
  container.append(h1, p);

  if (detail) {
    const id = detail[0];
    if (id.startsWith("STORY-")) renderStoryDetail(container, ctx, id);
    else renderReleaseDetail(container, ctx, id);
    return;
  }

  const releases = plan.releases || [];
  const schedule = plan.schedule || {};
  const stories = joinStories(plan, progress);

  container.appendChild(renderTimeline(releases, schedule));

  const h2 = document.createElement("h2");
  h2.textContent = "Tasks";
  container.appendChild(h2);

  const table = document.createElement("table");
  table.className = "data-table";
  table.innerHTML = `<thead><tr><th>Story</th><th>Release</th><th>Due</th><th>First given</th><th>Slippage</th><th>Status</th></tr></thead>`;
  const tbody = document.createElement("tbody");
  stories.forEach((s) => {
    const slippedDays = s.due_on && s.due_baseline_on ? Math.round((toUtcDay(s.due_on) - toUtcDay(s.due_baseline_on)) / DAY_MS) : 0;
    const tr = document.createElement("tr");
    tr.style.cursor = "pointer";
    tr.innerHTML = `
      <td><strong>${s.id}</strong> ${s.title}</td>
      <td>${s.release || "—"}</td>
      <td>${formatDate(s.due_on) || "—"}</td>
      <td>${formatDate(s.due_baseline_on) || "—"}</td>
      <td>${slippedDays === 0 ? "None" : `${slippedDays > 0 ? "+" : ""}${slippedDays}d`}</td>
      <td>${stateTagHtml(s.state)}</td>
    `;
    tr.onclick = () => navigate(`/project-management/${s.id}`);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);

  if ((schedule.prep || []).length) {
    const h3 = document.createElement("h2");
    h3.textContent = "Demo prep";
    container.appendChild(h3);
    const list = document.createElement("ul");
    list.className = "list-plain";
    list.innerHTML = schedule.prep.map((t) => `<li>${t.key} — ${t.title} (due ${formatDate(t.due_on)})</li>`).join("");
    container.appendChild(list);
  }
}

function renderTimeline(releases, schedule) {
  const wrap = document.createElement("div");
  wrap.className = "card";
  wrap.style.marginBottom = "24px";

  const rangeStart = toUtcDay(schedule.build_start);
  const rangeEnd = Math.max(toUtcDay(schedule.demo_day), toUtcDay(schedule.build_end));
  const totalDays = (rangeEnd - rangeStart) / DAY_MS;

  const pct = (iso) => ((toUtcDay(iso) - rangeStart) / DAY_MS / totalDays) * 100;

  const track = document.createElement("div");
  track.style.position = "relative";
  track.style.height = `${releases.length * 34 + 20}px`;

  releases.forEach((r, i) => {
    const left = pct(r.starts_on);
    const width = Math.max(pct(r.ends_on) - left, 2);
    const bar = document.createElement("button");
    bar.className = "card";
    bar.style.position = "absolute";
    bar.style.left = `${left}%`;
    bar.style.width = `${width}%`;
    bar.style.top = `${i * 34}px`;
    bar.style.height = "28px";
    bar.style.padding = "4px 8px";
    bar.style.fontSize = "12px";
    bar.style.fontWeight = "700";
    bar.style.background = r.is_demo_target ? "var(--accent)" : "var(--accent-weak)";
    bar.style.color = r.is_demo_target ? "#fff" : "var(--accent)";
    bar.style.border = "none";
    bar.style.borderRadius = "6px";
    bar.style.overflow = "hidden";
    bar.style.whiteSpace = "nowrap";
    bar.title = `${r.key} — ${r.name}${r.is_demo_target ? " (demo target)" : ""}`;
    bar.textContent = `${r.key}${r.is_demo_target ? " ★" : ""}`;
    bar.onclick = () => navigate(`/project-management/${r.key}`);
    track.appendChild(bar);
  });

  const demoMarker = document.createElement("div");
  demoMarker.style.position = "absolute";
  demoMarker.style.left = `${pct(schedule.demo_day)}%`;
  demoMarker.style.top = "0";
  demoMarker.style.bottom = "0";
  demoMarker.style.borderLeft = "2px dashed var(--danger)";
  track.appendChild(demoMarker);

  const today = new Date().toISOString().slice(0, 10);
  if (toUtcDay(today) >= rangeStart && toUtcDay(today) <= rangeEnd) {
    const todayMarker = document.createElement("div");
    todayMarker.style.position = "absolute";
    todayMarker.style.left = `${pct(today)}%`;
    todayMarker.style.top = "0";
    todayMarker.style.bottom = "0";
    todayMarker.style.borderLeft = "2px solid var(--ok)";
    track.appendChild(todayMarker);
  }

  const label = document.createElement("div");
  label.className = "card-sub";
  label.style.marginTop = "8px";
  label.textContent = `Build ${formatDate(schedule.build_start)} → ${formatDate(schedule.build_end)} · dashed line = demo day (${formatDate(
    schedule.demo_day
  )}) · green line = today · ★ = demo target release`;

  wrap.append(track, label);
  return wrap;
}

function renderReleaseDetail(container, ctx, key) {
  const { plan, progress } = ctx;
  renderCrumb(container, { label: key, onBack: () => navigate("/project-management") });
  const release = (plan.releases || []).find((r) => r.key === key);
  if (!release) {
    container.innerHTML += `<div class="empty-state"><h2>Not found</h2></div>`;
    return;
  }
  const h2 = document.createElement("h2");
  h2.textContent = `${release.key} — ${release.name}`;
  const goal = document.createElement("p");
  goal.textContent = release.goal;
  const demo = document.createElement("p");
  demo.className = "tab-desc";
  demo.innerHTML = `<strong>Demo:</strong> ${release.demo}`;
  container.append(h2, goal, demo);

  if (release.is_demo_target) {
    const badge = document.createElement("p");
    badge.innerHTML = `<span class="tag ok">Demo target</span> — this is this term's work; releases after it are the roadmap.`;
    container.appendChild(badge);
  }

  const stories = joinStories(plan, progress).filter((s) => (release.story_ids || []).includes(s.id));
  const list = document.createElement("ul");
  list.className = "list-plain";
  list.innerHTML = stories
    .map((s) => `<li><strong>${s.id}</strong> — ${s.title} ${stateTagHtml(s.state)}</li>`)
    .join("");
  container.appendChild(list);
}

function renderStoryDetail(container, ctx, storyId) {
  const { plan, progress } = ctx;
  renderCrumb(container, { label: storyId, onBack: () => navigate("/project-management") });
  const story = (plan.stories || []).find((s) => s.id === storyId);
  if (!story) {
    container.innerHTML += `<div class="empty-state"><h2>Not found</h2></div>`;
    return;
  }
  const p = (progress.stories || []).find((s) => s.id === storyId);
  const v = p?.verification;

  const h2 = document.createElement("h2");
  h2.textContent = `${story.id} — ${story.title}`;
  const narrative = document.createElement("p");
  narrative.textContent = story.narrative;
  const meta = document.createElement("p");
  meta.className = "tab-desc";
  meta.innerHTML = `Release ${story.release} · Owner ${story.owner_agent} · Due ${formatDate(story.due_on)} (first given ${formatDate(
    story.due_baseline_on
  )}) · ${stateTagHtml(v?.state ?? "not_started")}`;
  container.append(h2, narrative, meta);

  const h3 = document.createElement("h2");
  h3.textContent = "Acceptance criteria";
  container.appendChild(h3);
  const passedByText = new Map((p?.criteria || []).map((c) => [c.text, c.passed]));
  const list = document.createElement("ul");
  list.className = "list-plain";
  list.innerHTML = (story.acceptance || [])
    .map((text) => {
      const passed = passedByText.get(text);
      const tag = passed === true ? '<span class="tag ok">Passed</span>' : passed === false ? '<span class="tag unknown">Not yet</span>' : "";
      return `<li>${text} ${tag}</li>`;
    })
    .join("");
  container.appendChild(list);

  if ((story.failure_paths || []).length) {
    const h4 = document.createElement("h2");
    h4.textContent = "Failure paths considered";
    container.appendChild(h4);
    const fList = document.createElement("ul");
    fList.className = "list-plain";
    fList.innerHTML = story.failure_paths.map((f) => `<li>${f}</li>`).join("");
    container.appendChild(fList);
  }

  if (story.task_guidance) {
    const h5 = document.createElement("h2");
    h5.textContent = "Task guidance";
    const guidance = document.createElement("p");
    guidance.textContent = story.task_guidance;
    container.append(h5, guidance);
  }
}
