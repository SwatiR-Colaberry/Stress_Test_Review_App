"""One-off operational script: retrieve one Basecamp project's submissions
(REQ-004) through the OAuth 2.0 API client (REQ-012). Read-only.

Prints counts only: submission content is student data. With --save, writes
the full dataset as JSON to the git-ignored data/extracts/basecamp/ (atomic;
a re-run overwrites the same file).

Run from the repo root:
  .venv/bin/python backend/scripts/retrieve_submissions.py --project-id 123 --user-id you@colaberry.com
  .venv/bin/python backend/scripts/retrieve_submissions.py --demo --project-id 100 --user-id you   # fake Basecamp
Live mode needs BASECAMP_* in .env (see .env.example).
Exit codes: 0 ok, 1 configuration/input problem, 2 token rejected,
3 Basecamp unavailable or rate limited, 4 unexpected Basecamp response.
"""
import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

from app.basecamp.api_client import (  # noqa: E402
    BasecampAuthError, BasecampClient, BasecampRateLimited, BasecampResponseError, BasecampUnavailable,
)
from app.basecamp.config import BasecampConfigError, load_basecamp_config  # noqa: E402
from app.basecamp.demo_data import demo_config, demo_transport  # noqa: E402
from app.basecamp.submission_retrieval import retrieve_project_submissions  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.models import SubmissionDataset  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "data" / "extracts" / "basecamp"


def main(argv: Optional[List[str]] = None, output_dir: Path = OUTPUT_DIR) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--user-id", required=True, help="who is requesting the data (written to the audit log)")
    parser.add_argument("--demo", action="store_true", help="use the built-in fake Basecamp, not live data")
    parser.add_argument("--save", action="store_true", help="write the full dataset to data/extracts/basecamp/")
    args = parser.parse_args(argv)
    configure_logging()

    if args.demo:
        config, transport = demo_config(), demo_transport()
        print("DEMO MODE: fake Basecamp data, not live.")
    else:
        load_dotenv(REPO_ROOT / ".env", override=False)
        try:
            config, transport = load_basecamp_config(), None
        except BasecampConfigError as exc:
            print(f"CONFIG ERROR: {exc}")
            return 1

    try:
        with BasecampClient(config, transport=transport) as client:
            dataset = retrieve_project_submissions(client, args.project_id, args.user_id)
    except ValueError as exc:
        print(f"INPUT ERROR: {exc}")
        return 1
    except BasecampAuthError:
        print("TOKEN REJECTED: the OAuth token is invalid, expired, or cannot see this project. "
              "Re-authorize (basecamp_oauth_setup.py) or check project access.")
        return 2
    except (BasecampUnavailable, BasecampRateLimited) as exc:
        print(f"BASECAMP UNAVAILABLE: {exc}. Nothing was saved; safe to re-run.")
        return 3
    except BasecampResponseError as exc:
        if exc.status_code == 404:
            print(f"NOT FOUND: project {args.project_id} does not exist or this Basecamp login cannot see it.")
        else:
            print(f"UNEXPECTED RESPONSE: {exc}")
        return 4

    _print_summary(dataset)
    if args.save:
        print(f"Saved: {_save(dataset, output_dir, demo=args.demo)}")
    return 0


def _print_summary(dataset: SubmissionDataset) -> None:
    print(f"Project {dataset.project_id}: {len(dataset.submissions)} submissions")
    for s in dataset.submissions:
        comment_files = sum(len(c.attachments) for c in s.comments)
        comment_links = sum(len(c.links) for c in s.comments)
        print(f"  message {s.message_id}: {len(s.comments)} comments, "
              f"{len(s.attachments) + comment_files} attachments, {len(s.links) + comment_links} links")


def _save(dataset: SubmissionDataset, output_dir: Path, demo: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{'demo_' if demo else ''}project_{dataset.project_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


if __name__ == "__main__":
    sys.exit(main())
