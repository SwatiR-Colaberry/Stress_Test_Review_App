#!/usr/bin/env python3
"""One-off operational script: walks the repo and enforces REQ-016 — no
credentials stored in source code or shared documents. Exits non-zero if
anything is found. Run with
`python3 backend/scripts/scan_for_credentials.py` from the repo root.

Ported from the original Node.js implementation
(backend/src/scripts/scanForCredentials.js).
"""
import os
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

    for file_path in _walk(REPO_ROOT):
        if _is_test_fixture(file_path):
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

    print(f"No credential-shaped content found across {scanned} text files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
