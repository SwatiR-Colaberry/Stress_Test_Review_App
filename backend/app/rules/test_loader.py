"""STORY-003: only the identified Stress Test's rules are loaded; anything
uncertain routes to manual resolution with a reason code."""
import json
import shutil
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from app.audit.trail import AuditWriteError, InMemoryAuditTrail
from app.rules.loader import MAX_ATTEMPTS, MODULES_DIR, identify_stress_test, load_rules


@pytest.fixture
def modules(tmp_path):
    """A private copy of the real modules folder that tests may break."""
    shutil.copytree(MODULES_DIR, tmp_path / "modules")
    return tmp_path / "modules"


def _edit_st0(modules, **changes):
    path = modules / "ST0" / "v1.json"
    raw = json.loads(path.read_text())
    raw.update(changes)
    path.write_text(json.dumps(raw))


# Acceptance 1: a submission for ST0 loads only the ST0 rules.
def test_an_st0_submission_loads_only_st0_rules():
    result = load_rules("Stress Test 0 - Dataset & DS Problem - Retail Forecast", InMemoryAuditTrail())
    assert (result.outcome, result.stress_test_id, result.rule_version) == ("loaded", "ST0", "v1")
    assert {rule.id.split("-")[0] for rule in result.module.rules} == {"ST0"}
    assert result.reason_code is None


@pytest.mark.parametrize("label, expected", [
    ("Stress Test 0 - Dataset", "ST0"),
    ("stress test 3 - insights", "ST3"),
    ("Stress Test #1", "ST1"),
    ("StressTest 5", "ST5"),
])
def test_stress_test_is_identified_from_the_label(label, expected):
    assert identify_stress_test(label) == (expected, None)


# Acceptance 2: an unknown Stress Test routes to manual resolution.
@pytest.mark.parametrize("label, reason", [
    ("Stress Test 7 - Something new", "NO_RULE_MODULE"),
    ("Stress Test 10 - Capstone", "NO_RULE_MODULE"),
    ("Stress Test 2 - Dashboard", "NO_RULE_MODULE"),  # real Stress Test, no module yet
    ("Project kickoff notes", "STRESS_TEST_NOT_IDENTIFIED"),
    ("", "STRESS_TEST_NOT_IDENTIFIED"),
    (None, "STRESS_TEST_NOT_IDENTIFIED"),
    ("Stress Test 0 feedback, see Stress Test 1", "STRESS_TEST_AMBIGUOUS"),
])
def test_an_unknown_or_unclear_stress_test_routes_to_manual_resolution(label, reason):
    result = load_rules(label, InMemoryAuditTrail())
    assert (result.outcome, result.reason_code, result.module) == ("manual_resolution", reason, None)


# Failure path: rule module not found.
def test_a_missing_module_file_routes_to_manual_resolution(modules):
    (modules / "ST0" / "v1.json").unlink()
    result = load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules)
    assert (result.outcome, result.reason_code, result.rule_version) == ("manual_resolution", "RULE_MODULE_NOT_FOUND", "v1")


def test_a_missing_file_is_not_retried(modules):
    calls = []

    def read(path):
        calls.append(path.name)
        raise FileNotFoundError(path)

    assert load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules, read_text=read).reason_code == "RULE_MODULE_NOT_FOUND"
    assert calls == ["registry.json"]


# Failure path: incorrect rule version loaded.
def test_a_file_with_another_version_is_refused(modules):
    _edit_st0(modules, version="v2")  # registry asks for v1, file says v2
    result = load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules)
    assert (result.outcome, result.reason_code) == ("manual_resolution", "RULE_VERSION_MISMATCH")


def test_a_file_for_another_stress_test_is_refused(modules):
    # A valid ST1 module sitting where the ST0 v1 file should be.
    raw = json.loads((MODULES_DIR / "ST0" / "v1.json").read_text())
    raw["stress_test_id"] = "ST1"
    for rule in raw["rules"]:
        rule["id"] = rule["id"].replace("ST0", "ST1")
    for stage in raw["stages"]:
        stage["rule_ids"] = [rule_id.replace("ST0", "ST1") for rule_id in stage["rule_ids"]]
    (modules / "ST0" / "v1.json").write_text(json.dumps(raw))
    result = load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules)
    assert (result.outcome, result.reason_code) == ("manual_resolution", "RULE_VERSION_MISMATCH")


def test_an_invalid_module_file_routes_to_manual_resolution(modules):
    _edit_st0(modules, rules=[])
    assert load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules).reason_code == "RULE_MODULE_INVALID"
    (modules / "ST0" / "v1.json").write_text("{not json")
    assert load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules).reason_code == "RULE_MODULE_INVALID"


@pytest.mark.parametrize("registry", ['{"ST0": "../../secrets"}', '{"ST0": "v1"', '["ST0"]'])
def test_an_invalid_registry_routes_to_manual_resolution(modules, registry):
    (modules / "registry.json").write_text(registry)
    assert load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules).reason_code == "RULE_MODULE_INVALID"


# Failure path: rule loading timeout.
def test_a_read_that_never_finishes_times_out_after_capped_attempts(modules):
    release = threading.Event()
    calls = []

    def hang(path):
        calls.append(path.name)
        release.wait(5)
        return path.read_text()

    try:
        result = load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules, timeout_s=0.05, read_text=hang)
    finally:
        release.set()
    assert (result.outcome, result.reason_code) == ("manual_resolution", "RULE_LOAD_TIMEOUT")
    assert len(calls) == MAX_ATTEMPTS


def test_a_transient_read_error_is_retried_and_then_loads(modules):
    failures = iter([OSError("busy")])

    def flaky(path):
        error = next(failures, None)
        if error:
            raise error
        return path.read_text()

    assert load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules, read_text=flaky).outcome == "loaded"


def test_persistent_read_errors_give_up_after_capped_attempts(modules):
    calls = []

    def broken(path):
        calls.append(path.name)
        raise OSError("disk error")

    assert load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules, read_text=broken).reason_code == "RULE_LOAD_FAILED"
    assert len(calls) == MAX_ATTEMPTS


def test_loading_twice_gives_the_same_result():
    first, second = load_rules("Stress Test 0 - A", InMemoryAuditTrail()), load_rules("Stress Test 0 - A", InMemoryAuditTrail())
    assert first == second


def test_a_stress_test_number_longer_than_two_digits_is_not_identified():
    assert identify_stress_test("Stress Test 123 - X") == (None, "STRESS_TEST_NOT_IDENTIFIED")


# --- Acceptance 3 (Trust): rule loading events are logged with the rule version ---

class _BrokenAuditTrail(InMemoryAuditTrail):
    def record(self, event):
        raise AuditWriteError("disk full")


def _rule_log_lines(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "stress_test_review.rules"]


def test_a_successful_load_is_recorded_with_the_rule_version(caplog):
    caplog.set_level("INFO", logger="stress_test_review.rules")
    audit = InMemoryAuditTrail()
    load_rules("Stress Test 0 - A", audit, correlation_id="c-1", review_id="rev-9", comment_id=1001)
    [event] = audit.read_all()
    assert (event.action, event.outcome, event.stress_test_id, event.rule_version) == ("rules_loaded", "success", "ST0", "v1")
    assert (event.actor_id, event.correlation_id, event.review_id, event.comment_id) == ("system", "c-1", "rev-9", 1001)
    [line] = _rule_log_lines(caplog)
    assert (line["event"], line["rule_version"], line["correlation_id"]) == ("rules_loaded", "v1", "c-1")


@pytest.mark.parametrize("label, reason, version", [
    ("Stress Test 4 - Reporting", "NO_RULE_MODULE", None),
    ("Weekly update", "STRESS_TEST_NOT_IDENTIFIED", None),
])
def test_a_manual_resolution_is_recorded_with_its_reason(caplog, label, reason, version):
    caplog.set_level("INFO", logger="stress_test_review.rules")
    audit = InMemoryAuditTrail()
    load_rules(label, audit)
    [event] = audit.read_all()
    assert (event.action, event.outcome, event.reason_code, event.rule_version) == (
        "rules_manual_resolution", "blocked", reason, version)
    assert _rule_log_lines(caplog)[0]["level"] == "warning"


def test_a_version_mismatch_is_recorded_with_the_version_that_was_asked_for(modules):
    _edit_st0(modules, version="v2")
    audit = InMemoryAuditTrail()
    load_rules("Stress Test 0", audit, modules_dir=modules)
    [event] = audit.read_all()
    assert (event.reason_code, event.stress_test_id, event.rule_version) == ("RULE_VERSION_MISMATCH", "ST0", "v1")


def test_if_the_load_cannot_be_recorded_no_rules_are_returned(caplog):
    caplog.set_level("INFO", logger="stress_test_review.rules")
    with pytest.raises(AuditWriteError):
        load_rules("Stress Test 0 - A", _BrokenAuditTrail())
    [line] = _rule_log_lines(caplog)
    assert (line["event"], line["error_class"], line["rule_version"]) == ("audit_write_failed", "AuditWriteError", "v1")


def test_loading_twice_records_two_events_and_the_same_rules():
    audit = InMemoryAuditTrail()
    first, second = load_rules("Stress Test 0", audit), load_rules("Stress Test 0", audit)
    assert first.module == second.module
    assert [e.action for e in audit.read_all()] == ["rules_loaded", "rules_loaded"]


def test_an_unexpected_read_error_does_not_crash_the_loader(modules):
    def weird(path):
        raise ValueError("not an I/O error")

    assert load_rules("Stress Test 0", InMemoryAuditTrail(), modules_dir=modules, read_text=weird).reason_code == "RULE_LOAD_FAILED"


def test_a_hung_read_does_not_keep_the_process_alive():
    # Regression: with a thread pool, the process waited for the hung read at exit.
    backend = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(backend)!r})
        from app.audit.trail import InMemoryAuditTrail
        from app.rules.loader import load_rules
        result = load_rules("Stress Test 0", InMemoryAuditTrail(), timeout_s=0.05,
                            read_text=lambda path: time.sleep(60) or "")
        print(result.reason_code)
    """)
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
    assert done.stdout.strip() == "RULE_LOAD_TIMEOUT"
