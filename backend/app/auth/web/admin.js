// Admins page (STORY-014). Plain JavaScript, no build step.
//
// Lists everyone who can sign in; an admin adds someone, changes a role or
// removes someone. The server decides and audits every change; this page
// only asks and reports. Failure paths handled:
// - the list cannot load (network, timeout, 503) -> banner with Retry.
// - a change is refused (last admin, fixed admin, bad email) -> the reason
//   in plain words under the form; the list is reloaded so it shows the truth.
// - a change times out -> "nothing may have changed; reload to check"
//   (repeating a change is safe: the server answers "unchanged").
// - the session ended (401) -> sign in again; not an admin (403) -> said so.
// Emails are inserted with textContent, never as HTML.
"use strict";

const TIMEOUT_MS = 10000;
const $ = (id) => document.getElementById(id);
let me = null;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  children.flat().forEach((child) => child && node.append(child));
  return node;
}

// One request with a timeout. Resolves {ok, status, body, message}; never throws.
async function call(method, path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      method, signal: controller.signal,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    if (response.status === 401) Session.signInAgain();
    const data = await response.json().catch(() => null);
    const message = explainAuthFailure(response.status, data) || explainRoleFailure(response.status, data);
    return { ok: response.ok, status: response.status, body: data, message };
  } catch (err) {
    return { ok: false, status: 0, body: null, message: explainRoleFailure(0, null, err.name === "AbortError") };
  } finally {
    clearTimeout(timer);
  }
}

function showBanner(message, onRetry) {
  $("banner").hidden = false;
  $("banner-text").textContent = message;
  $("banner-retry").hidden = !onRetry;
  $("banner-retry").onclick = onRetry;
}

function say(message, ok) {
  $("status").className = `status ${ok ? "ok" : "bad"}`;
  $("status").textContent = message;
}

async function load() {
  const result = await call("GET", "/admin-ui/roles");
  if (!result.ok) {
    $("people").replaceChildren();
    showBanner(result.message, result.status === 0 || result.status === 503 ? load : null);
    return;
  }
  $("banner").hidden = true;
  $("people").replaceChildren(...result.body.map(row));
}

function row(person) {
  const isMe = me && me.email === person.email;
  const email = el("td", { class: "email" }, person.email,
    isMe ? el("span", { class: "you", text: "(you)" }) : null,
    person.bootstrap ? el("span", { class: "fixed", text: "(fixed admin)" }) : null);
  if (person.bootstrap) {
    return el("tr", {}, email, el("td", { text: "Admin" }), el("td", { class: "actions" }));
  }
  const select = el("select", { "aria-label": `Role for ${person.email}`, onchange: (e) => setRole(person.email, e.target.value) },
    el("option", { value: "reviewer", text: "Reviewer" }), el("option", { value: "admin", text: "Admin" }));
  select.value = person.role;
  const remove = el("button", { type: "button", class: "remove", text: "Remove", onclick: () => removePerson(person.email) });
  return el("tr", {}, email, el("td", {}, select), el("td", { class: "actions" }, remove));
}

async function setRole(email, role) {
  const result = await call("PUT", `/admin-ui/roles/${encodeURIComponent(email)}`, { role });
  if (result.ok) say(describeChange(result.body), true);
  else say(result.message, false);
  await load(); // show what the server now holds, refused or not
  return result.ok;
}

async function removePerson(email) {
  if (!window.confirm(`Remove ${email}? They will no longer be able to sign in.`)) return;
  const result = await call("DELETE", `/admin-ui/roles/${encodeURIComponent(email)}`);
  if (result.ok) say(describeChange(result.body), true);
  else say(result.message, false);
  await load();
}

$("add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("add-email").value.trim();
  if (!email) return;
  $("add-button").disabled = true;
  try {
    if (await setRole(email, $("add-role").value)) $("add-email").value = "";
  } finally {
    $("add-button").disabled = false;
  }
});

Session.ready.then((who) => { me = who; load(); });
