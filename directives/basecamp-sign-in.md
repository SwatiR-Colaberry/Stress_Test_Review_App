# Sign in with Basecamp — reviewers and admins

STORY-014 · REQ-020 ("Sign in with Basecamp as Reviewer or Admin").
Code: `backend/app/auth/` (settings, roles, sessions, sign-in, guards, page guard, Admins page in `web/`),
routes in `backend/app/routers/auth.py` and `backend/app/routers/admin.py`, wiring in `backend/app/main.py`.
Sign-in shares the posting app's Basecamp registration ("Stress Test Review App"), see
`directives/basecamp-connection-setup.md`; only its redirect URI changed.

## What it does

- Reviewers and admins sign in with their **Basecamp account**. The app matches them on their
  **Basecamp email** against its own list:
  - **Reviewer** — works the Review Queue, the reviewer page, the Rules page.
  - **Admin** — everything a reviewer can, plus the **Admins** page (`/admin/`): add, remove and
    change the role of reviewers and admins. Intake (`POST /basecamp/comments/process`) is admin-only too.
  - **Anyone else** — "Access refused", with the reason in plain words.
- Only `/health` and `/auth/*` are open. Every other page redirects to sign-in; every other API answers
  `401 NOT_SIGNED_IN` before it runs, so nothing is shown or changed. A Reviewer calling an admin-only
  API gets `403 ADMIN_ONLY` (audited).
- A session lasts **8 hours from sign-in** (activity does not extend it). **Sign out** ends it at once.
  Removing or demoting someone takes effect on their next click.
- Every reviewer action, view and post is recorded under the signed-in email. The old `X-Reviewer-Id`
  header is gone.

## The sign-in, step by step

1. `GET /auth/login` sets a one-use anti-forgery `state` cookie (10 minutes) and sends the browser to Basecamp.
2. The person clicks **Allow** in Basecamp; Basecamp sends them to `/auth/callback?code=…&state=…`.
3. The app checks, in order: sign-in configured → not cancelled → `state` matches → Basecamp confirms who
   it is (code exchange + `authorization.json`) → member of `BASECAMP_ACCOUNT_ID` → on the list.
4. Success: an HttpOnly, SameSite=Lax session cookie (Secure unless `AUTH_COOKIE_SECURE=no`), back to the
   page they asked for (paths on this site only). The Basecamp token is used once and thrown away.

## The settings (`.env`, never committed; names in `.env.example`)

| Variable | What |
|---|---|
| `AUTH_BOOTSTRAP_ADMIN_EMAILS` | Comma-separated emails that are **always admins** ("fixed admins"); they cannot be removed or demoted in the app, so the list can never lock everyone out. |
| `AUTH_BASECAMP_CLIENT_ID` / `AUTH_BASECAMP_CLIENT_SECRET` | The Basecamp integration used for sign-in: the **same** client id and secret as `BASECAMP_CLIENT_ID` / `BASECAMP_CLIENT_SECRET` (decision 2026-10-01, revised the same day: one registration, not two). A separate registration also works. |
| `AUTH_BASECAMP_REDIRECT_URI` | Must equal the registration exactly and end in `/auth/callback`. https, or `http://localhost:<port>/auth/callback` locally. |
| `AUTH_COOKIE_SECURE` | `yes` (default). `no` **only** for plain-http localhost. |
| `BASECAMP_ACCOUNT_ID`, `BASECAMP_USER_AGENT` | Shared with the posting app: only members of this account may sign in. |
| `AUTH_ROLES_PATH` | Optional; default `data/auth/roles.json` (git-ignored: staff emails). |

A missing value does not stop the app: sign-in shows "Sign-in is not set up on this server yet". A
malformed value (e.g. an http redirect on a real host) shows "not configured correctly" and the log line
`auth_config_invalid` names the variable, never its value.

## Setting it up (one time, by a person)

1. At <https://launchpad.37signals.com/integrations>, signed in as the Basecamp login that registered
   "Stress Test Review App", edit it and set its **Redirect URI** to `http://localhost:8000/auth/callback`
   for local use (the real https one when the app is hosted). No second registration is needed.
2. In `.env`: copy `BASECAMP_CLIENT_ID` / `BASECAMP_CLIENT_SECRET` into `AUTH_BASECAMP_CLIENT_ID` /
   `AUTH_BASECAMP_CLIENT_SECRET`, set `AUTH_BASECAMP_REDIRECT_URI` to the same redirect URI, your own
   Basecamp login email in `AUTH_BOOTSTRAP_ADMIN_EMAILS`, and `AUTH_COOKIE_SECURE=no` for localhost.
3. Start the app (`uvicorn app.main:app --app-dir backend --env-file .env --port 8000`), open
   `http://localhost:8000/queue/`, sign in, open **Admins** and add the reviewers by their Basecamp email.

## How success is verified

- `.venv/bin/python -m pytest backend/app/auth backend/scripts/test_signin_demo.py` — every acceptance line
  (`test_auth_routes.py`, `test_guards.py`, `test_roles.py`, `test_sessions.py`, `test_web_logic.py`).
  `test_guards.py` sweeps **every API in the app's OpenAPI schema**, so a new route left open fails the build.
- Offline demo, no Basecamp needed: `.venv/bin/python backend/scripts/signin_demo.py`, open
  `http://127.0.0.1:8014/queue/`, and choose who to be on the demo-only sign-in page (reviewer, admin,
  someone on no list, someone from another Basecamp account, cancel). The printed audit file shows each
  sign-in, refusal, sign-out and role change.
- Live: after the setup above, sign in as yourself (admin), as a reviewer, and as someone not on the list.
  Done for the admin path on 2026-10-01 by the project owner (reached the Admins page as a fixed admin;
  `signed_in` in the audit trail).

## The shared registration and the posting connection

A Launchpad app has one redirect URI, and it now points at `/auth/callback`. The posting tokens already in
`.env` are unaffected. To reconnect the posting app later (`backend/scripts/basecamp_oauth_setup.py`),
stop the app first (both use port 8000) and set `BASECAMP_REDIRECT_URI=http://localhost:8000/auth/callback`
in `.env` for that run.

## Audit and logs

| Audit action | When | Who / what |
|---|---|---|
| `signed_in` | session opened | actor = email, role |
| `sign_in_refused` | any refusal | actor = email (or `unidentified`), reason: `NOT_ON_LIST`, `NOT_IN_ACCOUNT`, `STATE_MISMATCH`, `BASECAMP_DENIED`, `BASECAMP_ERROR`, `ROLE_LIST_UNAVAILABLE`, `NOT_CONFIGURED` |
| `signed_out` | sign-out | actor = email |
| `role_added` / `role_changed` / `role_removed` | an admin's change (refused ones: outcome `blocked`, `LAST_ADMIN` / `BOOTSTRAP_ADMIN`) | actor = admin, subject = whose role, role |
| `admin_action_refused` | a Reviewer tried an admin-only API | actor = email, `ADMIN_ONLY` |

A request with no session is **logged** (`request_refused` / `page_refused`, JSON to stdout), not audited:
otherwise anyone could fill the audit file without signing in. Logs carry reason codes and error classes
only — never an email, token, OAuth code or secret. Uvicorn's access log, which prints every request URL,
has `code`, `state` and `*token*` query values replaced with `<redacted>` (`backend/app/logging_config.py`;
found in the first live sign-in, 2026-10-01). Emails live only in the git-ignored audit trail and role list.

## Failure modes

| What goes wrong | What happens |
|---|---|
| Basecamp slow / down / 5xx | Identity lookup: 15 s timeout, 3 attempts (1 s, 2 s). Code exchange: retried only if the request never left. Then "Basecamp could not confirm who you are… try again" (502). |
| Link opened twice, in another browser, or after 10 minutes | `STATE_MISMATCH`, "sign in again"; Basecamp is not called. |
| `roles.json` damaged or unreadable | Fail closed: only fixed admins can sign in; every other request is 503. The file is never overwritten. Fix or restore the file (it is plain JSON). |
| Audit trail cannot be written | A sign-in is **not** completed (503). A refusal or sign-out still happens (logged as error). A role change is undone. |
| Server restart | Sessions are in memory: everyone signs in again. |
| A garbage or oversized session cookie | Read as "not signed in": 401 / redirect to sign-in (not a 422), and sign-out still works. |
| Sign-in settings malformed | Pages and APIs answer 503 "not configured correctly" (never a crash); `auth_config_invalid` is logged with the variable name. |
| Session ended while a page is open | The next click goes to sign-in and comes back to the same page. Unsaved typed text is lost. |

Not handled: several server processes sharing sessions (sessions live in one process); single sign-out
from Basecamp (signing out of Basecamp does not end this app's session; it ends within 8 hours).
