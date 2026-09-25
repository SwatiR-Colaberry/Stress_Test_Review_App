#!/usr/bin/env python3
"""One-off operational script: walks the repo and enforces REQ-016 — no
credentials stored in source code or shared documents. Exits non-zero if
anything is found. Run with
`python3 backend/scripts/scan_for_credentials.py` from the repo root.

Ported from the original Node.js implementation
(backend/src/scripts/scanForCredentials.js).

Files that git ignores (e.g. the local .env, which is SUPPOSED to hold real
credentials, and data/extracts/) are skipped: they cannot be committed or
shared through the repo, which is what REQ-016 guards. Tracked files are
always scanned, even if they match an ignore pattern. If git is unavailable,
nothing is skipped (scanning more is the safe failure).
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.guardrails.credential_leak_guardrail import scan_text_for_credentials  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
SKIP_EXTENSIONS = {
    ".docx", ".doc", ".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mov", ".mp3",
}
MAX_BYTES = 2 * 1024 * 1024


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield os.path.join(dirpath, name)


def _git_ignored(paths, repo_root=None):
    """Subset of `paths` that git ignores (untracked and matching .gitignore).
    Returns an empty set if git cannot answer, so the caller scans everything."""
    paths = list(paths)
    if not paths:
        return set()
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            input="\0".join(paths) + "\0",
            cwd=repo_root or REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"note: git unavailable ({type(exc).__name__}); scanning ignored files too", file=sys.stderr)
        return set()
    # Exit 0: some paths ignored; 1: none ignored; anything else: git error.
    if result.returncode not in (0, 1):
        print("note: git check-ignore failed; scanning ignored files too", file=sys.stderr)
        return set()
    return {p for p in result.stdout.split("\0") if p}


def _is_likely_binary(data: bytes) -> bool:
    return b"\x00" in data


def _is_test_fixture(file_path: str) -> bool:
    # Test fixtures deliberately contain fake, credential-shaped values to
    # exercise the detectors themselves — that's the point of those tests.
    name = os.path.basename(file_path)
    return name.startswith("test_") or name.endswith("_test.py") or name.endswith(".test.js")


def main() -> int:
    all_findings = []
    scanned = 0
    candidates = list(_walk(REPO_ROOT))
    ignored = _git_ignored(candidates)

    for file_path in candidates:
        if file_path in ignored or _is_test_fixture(file_path):
            continue
        ext = os.path.splitext(file_path)[1].lower()
        if ext in SKIP_EXTENSIONS:
            continue

        try:
            size = os.path.getsize(file_path)
        except OSError:
            continue
        if size == 0 or size > MAX_BYTES:
            continue

        try:
            with open(file_path, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if _is_likely_binary(data):
            continue

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue

        scanned += 1
        relative_path = os.path.relpath(file_path, REPO_ROOT)
        for finding in scan_text_for_credentials(text):
            all_findings.append({**finding, "file": relative_path})

    if all_findings:
        print(f"Credential-shaped content found ({len(all_findings)}):", file=sys.stderr)
        for f in all_findings:
            print(f"  {f['file']}:{f['line']}  {f['pattern']}", file=sys.stderr)
        print(
            "\nRemove or redact the value above, or move it to an env var, before committing.",
            file=sys.stderr,
        )
        return 1

    print(f"No credential-shaped content found across {scanned} text files "
          f"({len(ignored)} git-ignored files skipped).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
