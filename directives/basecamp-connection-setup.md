# Basecamp connection — setup, verification and handover

How this app gets access to Colaberry's Basecamp, how to set it up on a new machine or for a new
person, and what to do when the person who set it up leaves or their email changes.

Code: `backend/app/basecamp/config.py`, `oauth.py`, `api_client.py`; scripts
`backend/scripts/basecamp_oauth_setup.py` and `check_basecamp_connection.py`.
Requirements: REQ-004 (retrieval), REQ-012 (OAuth 2.0), REQ-007 (posting, STORY-006).

## How the access works (read this first)

Basecamp has no API keys. Access has **two parts, and each is tied to a person**:

| Part | What it is | Tied to | Where it lives |
|---|---|---|---|
| **App registration** | "Stress Test Review App" at launchpad.37signals.com/integrations. Gives a **Client ID** and **Client Secret**. | The Basecamp login that **registered** it. Only that login can see the secret, reset it, change the redirect URI or delete the app. | Launchpad. The ID and secret are copied into `.env`. |
| **Authorization (tokens)** | An **access token** (about 2 weeks) and a **refresh token**, made when someone clicks **Allow**. | The Basecamp login that **clicked Allow**. The app reads and posts **as that person**: posted feedback shows their name. It sees only the projects that person can see. | `.env` only. |

So if either person loses their Basecamp login (they leave, their email changes, they are removed
from the Colaberry account), part of the setup stops working. Follow **Handover** below *before*
that happens.

**Decision (project owner, 2026-09-30): no shared login.** The app keeps running under a named
person's Basecamp login, and posted feedback shows that person's name. Keep the Client Secret in the
company password manager, and follow **Handover** below before that person's login changes.

## Current state (2026-09-30)

- App "Stress Test Review App" registered on Launchpad by the project owner (Swati) with their own
  Basecamp login. Products: **Basecamp 5**. Redirect URI:
  `http://localhost:8765/basecamp/oauth/callback` (development: the setup script on a laptop).
- Authorized once on the project owner's laptop (session CC-20260930-umhk). The Tableau and Power BI
  projects are both readable; each has 6 message boards.
- Real posting is **off** (`BASECAMP_POSTING_ENABLED=no`) until STORY-014 (reviewer sign-in).
- **Decision (project owner, 2026-09-30): no shared login**, so posts show the authorizing
  person's name. An earlier plan to move to a shared team login was dropped the same day.

## The settings (`.env`, never committed)

`.env` is git-ignored and must stay that way; `.env.example` lists the names with no values.

| Variable | Filled by | Notes |
|---|---|---|
| `BASECAMP_CLIENT_ID` | you, from the app's Launchpad page | |
| `BASECAMP_CLIENT_SECRET` | you, from the app's Launchpad page | A password: never in chat, email, Basecamp or git |
| `BASECAMP_REDIRECT_URI` | you | Must match the registration exactly: `http://localhost:8765/basecamp/oauth/callback` |
| `BASECAMP_USER_AGENT` | you | `Stress Test Review App (<team email that is read>)`. Basecamp contacts this address about problems and rejects calls without it. Use a team address, not a personal one. |
| `BASECAMP_ACCOUNT_ID` | the setup script | Colaberry's Basecamp account number |
| `BASECAMP_ACCESS_TOKEN`, `BASECAMP_REFRESH_TOKEN` | the setup script | Never printed or logged |
| `BASECAMP_POSTING_ENABLED` | you | `no` until STORY-014 is done |
| `BASECAMP_POSTING_PROJECT_IDS` | you | Comma-separated project ids feedback may be posted into; the id is the number in `…/projects/<id>` |
| `BASECAMP_POSTING_TIME_LIMIT_S` | optional | Default 60 |

## Setup on a new machine (the app is already registered)

1. Clone the repo and install (see README: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`).
2. `cp .env.example .env`, then fill `BASECAMP_CLIENT_ID`, `BASECAMP_CLIENT_SECRET`,
   `BASECAMP_REDIRECT_URI` and `BASECAMP_USER_AGENT`. Get the ID and secret from the app owner
   (password manager), or on Launchpad: **Your Applications → click "Stress Test Review App"**.
3. Authorize: `.venv/bin/python backend/scripts/basecamp_oauth_setup.py`. The browser opens;
   sign in as the Basecamp user the app should act as and click **Allow** within 3 minutes.
   The script writes `BASECAMP_ACCOUNT_ID`, `BASECAMP_ACCESS_TOKEN`, `BASECAMP_REFRESH_TOKEN`
   into `.env` (mode 600). Exit codes: 0 ok, 1 settings missing (it names them), 2 authorization
   failed, 3 no Basecamp account found / account choice needed (re-run with `--account-id N`).
4. Verify (read-only, one call, changes nothing):
   `.venv/bin/python backend/scripts/check_basecamp_connection.py --project-id <project id>`
   Expect `OK: Basecamp token accepted and the project is readable`.

## Registering the app from scratch (only when there is no usable registration)

1. Sign in at https://launchpad.37signals.com/integrations with the login that should **own** the
   app → **Register another application**.
2. Fill in: Name `Stress Test Review App` · Company `Colaberry` · Website `https://colaberry.com`
   · Icon: skip · Products: tick **Basecamp 5** only · Redirect URI
   `http://localhost:8765/basecamp/oauth/callback` (exactly: `http`, port 8765, no trailing slash).
3. Register, then click the app's name to see the Client ID and Client Secret. Store the secret in
   the password manager, then continue with **Setup on a new machine**, step 2.

## Handover (someone leaves, or their email/login changes)

Do this while the old login still works.

1. **Who authorized (posts appear under their name)?** Re-run step 3 of the setup signed in as the
   new person's login. The new tokens replace the old ones in `.env`. Verify with step 4.
2. **Who owns the registration?** Either the owner hands it over — check on Launchpad whether the
   app can be transferred; if it cannot — **register a new app** under the new owner (section
   above), put its Client ID/Secret in `.env`, and re-authorize. No code changes: everything is
   read from `.env`.
3. **Clean up:** the old owner deletes the old registration on Launchpad (this also invalidates its
   tokens) after the new one is verified. Update the "Current state" section above and the
   password manager entry.
4. **Deployed servers** (none yet): update their secret settings the same way.

If the old login is already gone: register a new app and authorize again (sections above). The old
registration stops working when its owner's Basecamp login is removed; nothing in the repo needs to
be cleaned up because no secret was ever stored there.

## Routine care and incidents

- **Token expired** (about every 2 weeks; `TOKEN REJECTED` / exit 2 from the check, `AuthError` in
  logs): re-run `basecamp_oauth_setup.py`. Automatic refresh with the refresh token is not built yet.
- **Client Secret leaked** (pasted in chat, committed, emailed): on Launchpad reset/regenerate the
  secret (or delete and re-register the app), update `.env`, re-run the setup script, run the check.
  If it was committed, treat it as compromised even after deleting it (CLAUDE.md, Secrets).
- **Moving to a server** (production): register a **separate** app whose Redirect URI is the
  server's https address (needed once reviewers sign in on the server, STORY-014). Put its values
  in the server's secret settings, not a copied laptop `.env`. The dev registration stays for laptops.

## How success is verified

- `check_basecamp_connection.py --project-id <id>` prints `OK` and exits 0.
- `git status` never shows `.env`; `python3 backend/scripts/scan_for_credentials.py` is clean.
- `pytest backend` passes (`backend/app/basecamp/test_oauth.py`, `test_config.py`,
  `backend/scripts/test_check_basecamp_connection.py` — none of them touch the real Basecamp).

## Known limits (found 2026-09-30)

- The Tableau and Power BI projects each have **6 message boards**, but submission retrieval
  (STORY-002, `submission_retrieval.py`) reads only the **first** one. Retrieval misses the others
  until that is fixed. Posting (STORY-006) is not affected: it posts to the message's own thread.
