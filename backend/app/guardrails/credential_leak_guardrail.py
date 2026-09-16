"""Enforces REQ-016: no credentials stored in source code or shared
documents. Pure and synchronous; never includes the matched secret value
itself in its output or in an error message, only the detector name and
line number.

Ported from the original Node.js implementation
(backend/src/services/guardrails/credentialLeakGuardrail.js); every
detector, the placeholder allowlist, and the line-numbering scheme are
preserved exactly.
"""
import re
from typing import List, Optional, TypedDict


class CredentialFinding(TypedDict):
    pattern: str
    line: int


class CredentialLeakError(Exception):
    def __init__(self, findings: List[CredentialFinding], source_label: Optional[str] = None):
        summary = "; ".join(f"{f['pattern']} at line {f['line']}" for f in findings)
        super().__init__(f"Credential-shaped content found in {source_label or 'source'}: {summary}")
        self.name = "CredentialLeakError"
        self.error_class = "ContractViolation"
        self.findings = findings
        self.source_label = source_label


# Values that look like they're assigned to a secret-shaped key but are not
# real secrets: placeholders, env-var interpolation, angle-bracket
# instructions, redaction markers. Never flag these.
def _is_placeholder_value(value: str) -> bool:
    v = value.strip()
    if v == "":
        return True
    if re.fullmatch(r"(x{3,}|\*{3,}|-{3,}|\.{3,})", v, re.IGNORECASE):
        return True
    if re.match(
        r"(your[_-]?|replace[_-]?me|change[_-]?me|placeholder|example|dummy|fake|sample|redacted|todo)",
        v,
        re.IGNORECASE,
    ):
        return True
    if re.fullmatch(r"<.*>", v):
        return True
    if re.fullmatch(r"\$\{.*\}", v):
        return True
    if re.fullmatch(r"%[A-Z_]+%", v):
        return True
    return False


# Fixed-format secrets: matching the shape alone is enough to flag them.
_SHAPED_DETECTORS = [
    ("AWS_ACCESS_KEY_ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("ANTHROPIC_API_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("OPENAI_STYLE_API_KEY", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("PRIVATE_KEY_BLOCK", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----")),
]

# Assignment-shaped secrets: a secret-sounding key bound to a non-placeholder
# literal value, e.g. a credential hardcoded directly in a config or source
# file, as opposed to a process.env.X / os.environ[...] reference or a
# placeholder value, neither of which this should flag.
_ASSIGNMENT_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|password|passwd|token|client[_-]?secret|auth[_-]?token)", re.IGNORECASE
)
_ASSIGNMENT_REGEX = re.compile(
    r"([A-Za-z0-9_.-]*(?:api[_-]?key|secret|password|passwd|token|client[_-]?secret|auth[_-]?token)"
    r"[A-Za-z0-9_.-]*)"
    r"\s*[:=]\s*"
    r"""(?:["']([^"'\n]{8,})["']|([A-Za-z0-9/+_=-]{12,})(?=[\s,;)]|$))""",
    re.IGNORECASE,
)


def _line_number_at(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def scan_text_for_credentials(content) -> List[CredentialFinding]:
    """Scans text content for credential-shaped strings."""
    if not isinstance(content, str) or len(content) == 0:
        return []

    findings: List[CredentialFinding] = []

    for pattern, regex in _SHAPED_DETECTORS:
        for match in regex.finditer(content):
            findings.append({"pattern": pattern, "line": _line_number_at(content, match.start())})

    for match in _ASSIGNMENT_REGEX.finditer(content):
        key = match.group(1)
        value = match.group(2) if match.group(2) is not None else match.group(3)
        if not _ASSIGNMENT_KEY_PATTERN.search(key):
            continue
        if _is_placeholder_value(value):
            continue
        # process.env.X / os.environ[...] references have no literal value to
        # capture in the first place, so they never reach this branch.
        findings.append({"pattern": "GENERIC_SECRET_ASSIGNMENT", "line": _line_number_at(content, match.start())})

    findings.sort(key=lambda f: f["line"])
    return findings


def assert_no_credential_leaks(content, source_label: Optional[str] = None) -> dict:
    findings = scan_text_for_credentials(content)
    if findings:
        raise CredentialLeakError(findings, source_label)
    return {"safe": True}
