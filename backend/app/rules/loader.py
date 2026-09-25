"""Rule loading (STORY-003: REQ-003).

Given a submission's Stress Test label (the step or message title, e.g.
"Stress Test 0 - Dataset & DS Problem"), load ONLY that Stress Test's rule
module, at the version the registry names. Anything uncertain goes to manual
resolution instead of a guess (Master Spec §6, §23):

  reason_code                 when
  STRESS_TEST_NOT_IDENTIFIED  no "Stress Test N" in the label
  STRESS_TEST_AMBIGUOUS       two different Stress Test numbers in the label
  NO_RULE_MODULE              the Stress Test is not in the registry (ST1-ST5
                              today, or an unknown one like "Stress Test 10")
  RULE_MODULE_NOT_FOUND       the registry names a file that does not exist
  RULE_MODULE_INVALID         the registry or module file fails validation
  RULE_VERSION_MISMATCH       the file's own stress_test_id/version differ from
                              what was asked for (incorrect version loaded)
  RULE_LOAD_TIMEOUT           reading did not finish within the time limit
  RULE_LOAD_FAILED            reading failed for another I/O reason

load_rules() never raises for these: a bad module must not crash a review.

Every call is recorded (Trust criterion): one AuditEvent, rules_loaded with
the Stress Test and rule version, or rules_manual_resolution with the reason
code (and the version when one was involved), plus a matching JSON log line.
The audit trail is a required argument, so rules cannot be loaded unrecorded;
if the audit write fails, AuditWriteError is raised instead of returning
rules nobody can trace.
Reads are bounded: each attempt has a timeout, and at most MAX_ATTEMPTS
attempts are made for transient errors (timeouts, I/O errors). A missing or
invalid file is not retried; it will not fix itself. Read-only, so safe to
call any number of times.

Adding ST1 later = add modules/ST1/v1.json and one registry line (REQ-017).
"""
import json
import logging
import re
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, RootModel, ValidationError, field_validator

from app.audit.trail import AuditTrail, AuditWriteError
from app.models import AuditEvent
from app.rules.module import RuleModule

logger = logging.getLogger("stress_test_review.rules")

MODULES_DIR = Path(__file__).resolve().parent / "modules"
DEFAULT_TIMEOUT_S = 5.0
MAX_ATTEMPTS = 3

ReasonCode = Literal[
    "STRESS_TEST_NOT_IDENTIFIED",
    "STRESS_TEST_AMBIGUOUS",
    "NO_RULE_MODULE",
    "RULE_MODULE_NOT_FOUND",
    "RULE_MODULE_INVALID",
    "RULE_VERSION_MISMATCH",
    "RULE_LOAD_TIMEOUT",
    "RULE_LOAD_FAILED",
]

# 1-2 digits: "Stress Test 123" is not a Stress Test number (and keeps ids short).
_STRESS_TEST = re.compile(r"\bstress\s*test\s*#?\s*(\d{1,2})\b", re.IGNORECASE)


class RuleLoadResult(BaseModel):
    """Either the loaded module, or a manual-resolution result with a reason."""
    outcome: Literal["loaded", "manual_resolution"]
    stress_test_id: Optional[str] = None
    rule_version: Optional[str] = None
    reason_code: Optional[ReasonCode] = None
    module: Optional[RuleModule] = None


class RuleRegistry(RootModel[Dict[str, str]]):
    """{"ST0": "v1", ...}: which version of each Stress Test's rules is active."""

    @field_validator("root")
    @classmethod
    def _valid_entries(cls, entries: Dict[str, str]) -> Dict[str, str]:
        for stress_test_id, version in entries.items():
            if not re.fullmatch(r"ST[0-9]", stress_test_id) or not re.fullmatch(r"v[0-9]+", version):
                raise ValueError(f"invalid registry entry {stress_test_id!r}: {version!r}")
        return entries


def identify_stress_test(label: Optional[str]) -> Tuple[Optional[str], Optional[ReasonCode]]:
    """'Stress Test 0 - Dataset' -> ('ST0', None). Never guesses: returns a
    reason code when there is no number or two different ones. 'Stress Test
    10' gives 'ST10', which no registry entry matches (NO_RULE_MODULE)."""
    numbers = {int(n) for n in _STRESS_TEST.findall(label or "")}
    if not numbers:
        return None, "STRESS_TEST_NOT_IDENTIFIED"
    if len(numbers) > 1:
        return None, "STRESS_TEST_AMBIGUOUS"
    return f"ST{numbers.pop()}", None


class _ReadFailed(Exception):
    def __init__(self, reason_code: ReasonCode) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


ReadText = Callable[[Path], str]


def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_rules(
    stress_test_label: Optional[str],
    audit: AuditTrail,
    *,
    actor_id: str = "system",
    correlation_id: Optional[str] = None,
    review_id: Optional[str] = None,
    comment_id: Optional[int] = None,
    modules_dir: Path = MODULES_DIR,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    read_text: Optional[ReadText] = None,
) -> RuleLoadResult:
    """The only entry point: identify, load, record. review_id/comment_id tie
    the audit event to the submission being reviewed, when known."""
    stress_test_id, reason = identify_stress_test(stress_test_label)
    if reason:
        result = RuleLoadResult(outcome="manual_resolution", reason_code=reason)
    else:
        result = _load_module(stress_test_id, modules_dir, timeout_s, read_text or _read_file)
    _record(audit, result, actor_id, correlation_id or str(uuid.uuid4()), review_id, comment_id)
    return result


def _load_module(stress_test_id: str, modules_dir: Path, timeout_s: float, read_text: ReadText) -> RuleLoadResult:
    def manual(reason_code: ReasonCode, version: Optional[str] = None) -> RuleLoadResult:
        return RuleLoadResult(outcome="manual_resolution", stress_test_id=stress_test_id,
                              rule_version=version, reason_code=reason_code)

    try:
        registry = RuleRegistry.model_validate(json.loads(_read(modules_dir / "registry.json", timeout_s, read_text)))
    except _ReadFailed as exc:
        return manual(exc.reason_code)
    except (json.JSONDecodeError, ValidationError):
        return manual("RULE_MODULE_INVALID")

    version = registry.root.get(stress_test_id)
    if version is None:
        return manual("NO_RULE_MODULE")
    try:
        module = RuleModule.model_validate_json(_read(modules_dir / stress_test_id / f"{version}.json", timeout_s, read_text))
    except _ReadFailed as exc:
        return manual(exc.reason_code, version)
    except ValidationError:
        return manual("RULE_MODULE_INVALID", version)
    if (module.stress_test_id, module.version) != (stress_test_id, version):
        return manual("RULE_VERSION_MISMATCH", version)
    return RuleLoadResult(outcome="loaded", stress_test_id=stress_test_id, rule_version=version, module=module)


def _record(
    audit: AuditTrail,
    result: RuleLoadResult,
    actor_id: str,
    correlation_id: str,
    review_id: Optional[str],
    comment_id: Optional[int],
) -> None:
    loaded = result.outcome == "loaded"
    event = AuditEvent(
        event_id=str(uuid.uuid4()),
        recorded_at=datetime.now(timezone.utc),
        action="rules_loaded" if loaded else "rules_manual_resolution",
        actor_id=actor_id,
        outcome="success" if loaded else "blocked",
        correlation_id=correlation_id,
        review_id=review_id,
        comment_id=comment_id,
        stress_test_id=result.stress_test_id,
        rule_version=result.rule_version,
        reason_code=result.reason_code,
    )
    context: Dict[str, Any] = {
        "stress_test_id": result.stress_test_id,
        "rule_version": result.rule_version,
        "reason_code": result.reason_code,
        "review_id": review_id,
        "comment_id": comment_id,
    }
    try:
        audit.record(event)
    except AuditWriteError:
        _log(logging.ERROR, "audit_write_failed", correlation_id, audit_action=event.action,
             outcome="failure", error_class=AuditWriteError.error_class, **context)
        raise
    _log(logging.INFO if loaded else logging.WARNING, event.action, correlation_id,
         outcome=event.outcome, **context)


def _log(level: int, event: str, correlation_id: str, **context: Any) -> None:
    line = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": logging.getLevelName(level).lower(),
        "service": "backend",
        "event": event,
        "correlation_id": correlation_id,
        **context,
    }
    logger.log(level, json.dumps(line))


def _read(path: Path, timeout_s: float, read_text: ReadText) -> str:
    """Reads with a per-attempt timeout; retries transient failures up to
    MAX_ATTEMPTS times, so the worst case is MAX_ATTEMPTS x timeout_s per file.
    A missing file is reported at once."""
    last: ReasonCode = "RULE_LOAD_FAILED"
    for _attempt in range(MAX_ATTEMPTS):
        outcome: Dict[str, Any] = {}

        def attempt() -> None:
            try:
                outcome["text"] = read_text(path)
            except Exception as exc:  # noqa: BLE001 — thread boundary: any error is handed back, classified below
                outcome["error"] = exc

        # A daemon thread: if the read hangs, the caller gets control back
        # after timeout_s AND the process can still exit (a thread-pool worker
        # would be joined at exit and keep the process alive until it ends).
        worker = threading.Thread(target=attempt, name="rule-module-read", daemon=True)
        worker.start()
        worker.join(timeout_s)
        if worker.is_alive():
            last = "RULE_LOAD_TIMEOUT"
        elif isinstance(outcome.get("error"), FileNotFoundError):
            raise _ReadFailed("RULE_MODULE_NOT_FOUND")
        elif "text" in outcome:
            return outcome["text"]
        else:  # OSError, UnicodeDecodeError, or anything unexpected from the reader
            last = "RULE_LOAD_FAILED"
    raise _ReadFailed(last)
