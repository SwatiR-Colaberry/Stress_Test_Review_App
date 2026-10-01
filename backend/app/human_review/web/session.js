// Signed-in bar for every reviewer page (STORY-014). Plain JavaScript, no
// build step. Needs session_logic.js loaded first and an element with
// id="who" in the app bar.
//
// - Shows who is signed in, their role, and a Sign out button (a form POST,
//   so it works even if this script fails later).
// - Admins also get an "Admins" link in the page navigation.
// - Session.signInAgain() sends the browser to sign in, coming back here.
//   Pages call it on any 401: the session ended (8 hours, or signed out in
//   another tab), so nothing more can be shown or saved.
// Names are inserted with textContent, never as HTML.
"use strict";

const Session = (() => {
  function signInAgain() {
    window.location.assign(signInUrl(window.location.pathname + window.location.search, true));
  }

  function render(me) {
    const who = document.getElementById("who");
    if (!who) return;
    const name = document.createElement("span");
    name.className = "who-name";
    name.textContent = me.name;
    name.title = me.email;
    const role = document.createElement("span");
    role.className = "who-role";
    role.textContent = roleLabel(me.role);
    const form = document.createElement("form");
    form.method = "post";
    form.action = "/auth/logout";
    const button = document.createElement("button");
    button.type = "submit";
    button.textContent = "Sign out";
    form.append(button);
    who.replaceChildren(name, role, form);
    const nav = document.querySelector(".nav");
    if (me.role === "admin" && nav && !nav.querySelector('a[href="/admin/"]')) {
      const link = document.createElement("a");
      link.href = "/admin/";
      link.textContent = "Admins";
      if (window.location.pathname.startsWith("/admin")) link.setAttribute("aria-current", "page");
      nav.append(link);
    }
  }

  // Resolves to {email, name, role, expires_at}, or null when it could not be
  // read (the page then still works; its own API calls report any problem).
  // Capped at 10 s like every other request on these pages, so a hung server
  // cannot leave a page (e.g. Admins, which waits for this) waiting forever.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  const ready = fetch("/auth/me", { headers: { Accept: "application/json" }, signal: controller.signal })
    .then(async (response) => {
      if (response.status === 401) { signInAgain(); return null; }
      if (!response.ok) return null;
      const me = await response.json();
      render(me);
      return me;
    })
    .catch((err) => { console.warn("could not read who is signed in:", err.name); return null; })
    .finally(() => clearTimeout(timer));

  return { ready, signInAgain };
})();
