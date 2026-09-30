"""Read-only check that this machine's Basecamp connection works: one GET of
one project. Changes nothing in Basecamp. Prints the result and counts only,
never a token, a name or any content.

Run from the repo root (see directives/basecamp-connection-setup.md):
  .venv/bin/python backend/scripts/check_basecamp_connection.py --project-id <id from .../projects/<id>>

Exit codes: 0 connected; 1 settings missing/invalid; 2 token rejected (re-run
basecamp_oauth_setup.py, or the authorizing user lost access); 3 Basecamp
unreachable or rate limited; 4 unexpected answer (e.g. project not found or
not visible to the authorizing user).
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

from app.basecamp.api_client import (  # noqa: E402
    BasecampAuthError,
    BasecampClient,
    BasecampRateLimited,
    BasecampResponseError,
    BasecampUnavailable,
)
from app.basecamp.config import BasecampConfigError, load_basecamp_config  # noqa: E402


def main(argv: Optional[List[str]] = None, transport: Optional[httpx.BaseTransport] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-id", type=int, required=True, help="Basecamp project id (from its URL)")
    args = parser.parse_args(argv)
    if args.project_id <= 0:
        print("CONFIG ERROR: --project-id must be a positive number")
        return 1

    load_dotenv(REPO_ROOT / ".env", override=False)
    try:
        config = load_basecamp_config()
    except BasecampConfigError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1
    try:
        with BasecampClient(config, transport=transport, max_attempts=2, sleep=lambda s: None) as client:
            project = client.get_json(f"/projects/{args.project_id}.json")
    except BasecampAuthError:
        print("TOKEN REJECTED: re-run backend/scripts/basecamp_oauth_setup.py "
              "(token expired, or the authorizing Basecamp user lost access)")
        return 2
    except (BasecampUnavailable, BasecampRateLimited) as exc:
        print(f"BASECAMP UNAVAILABLE: {exc.error_class}; try again later")
        return 3
    except BasecampResponseError as exc:
        print(f"UNEXPECTED ANSWER: {exc.error_class} (status {exc.status_code}); "
              "check the project id and that the authorizing user can see this project")
        return 4
    dock = project.get("dock") if isinstance(project, dict) else None
    if not isinstance(dock, list):
        print("UNEXPECTED ANSWER: project has no dock list")
        return 4
    boards = [tool for tool in dock if isinstance(tool, dict) and tool.get("name") == "message_board"]
    print("OK: Basecamp token accepted and the project is readable")
    print(f"  message boards in this project: {len(boards)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
