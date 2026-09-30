"""The Rules page (STORY-012): built from the rule files, one module at a time."""
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app.audit.dependencies import get_audit_trail
from app.audit.trail import InMemoryAuditTrail
from app.main import app
from app.routers.rules_ui import get_modules_dir
from app.rules.loader import MODULES_DIR
from app.rules_ui.service import RulesReadError, rules_page, stress_test_name

REVIEWER = {"X-Reviewer-Id": "reviewer-7"}


@pytest.fixture
def modules(tmp_path):
    """A copy of the real modules folder, safe to break."""
    target = tmp_path / "modules"
    shutil.copytree(MODULES_DIR, target)
    return target


def _add_st1(modules, text=None, registry_version="v1"):
    registry = json.loads((modules / "registry.json").read_text())
    registry["ST1"] = registry_version
    (modules / "registry.json").write_text(json.dumps(registry))
    if text is not None:
        (modules / "ST1").mkdir()
        (modules / "ST1" / "v1.json").write_text(text)


def test_the_real_st0_rules_are_shown_by_stage_with_examples():
    [st0] = rules_page().modules
    assert (st0.name, st0.version, st0.available) == ("Stress Test 0", "v1", True)
    assert [s.number for s in st0.stages] == [1, 2, 3]
    assert st0.stages[2].kind == "advisory" and st0.stages[2].rules == [] and st0.stages[2].instructions
    assert [r.id for s in st0.stages for r in s.rules] == [
        "ST0-001", "ST0-002", "ST0-003", "ST0-006", "ST0-007", "ST0-008", "ST0-004", "ST0-005"]
    assert st0.stages[0].blocking is True
    assert all(r.example for s in st0.stages for r in s.rules)
    assert st0.problem_count.min == 8 and "Dependent Variable" in st0.required_problem_fields


def test_a_new_stress_test_appears_by_adding_its_file_and_registry_line(modules):
    raw = json.loads((modules / "ST0" / "v1.json").read_text())
    text = json.dumps(raw).replace("ST0-", "ST1-").replace('"stress_test_id": "ST0"', '"stress_test_id": "ST1"')
    _add_st1(modules, text)
    names = [(m.name, m.available) for m in rules_page(modules).modules]
    assert names == [("Stress Test 0", True), ("Stress Test 1", True)]


@pytest.mark.parametrize("text, registry_version, reason", [
    (None, "v1", "RULE_MODULE_NOT_FOUND"),
    ("{not json", "v1", "RULE_MODULE_INVALID"),
    (None, "v2", "RULE_MODULE_NOT_FOUND"),
])
def test_one_broken_module_is_marked_and_the_others_still_show(modules, text, registry_version, reason):
    _add_st1(modules, text, registry_version)
    st0, st1 = rules_page(modules).modules
    assert st0.available and not st1.available
    assert st1.reason_code == reason and st1.stages == []


def test_a_file_naming_another_stress_test_is_not_shown(modules):
    _add_st1(modules, (modules / "ST0" / "v1.json").read_text())  # ST1 slot holds the ST0 file
    assert rules_page(modules).modules[1].reason_code == "RULE_VERSION_MISMATCH"


def test_an_unreadable_registry_is_a_clear_error(modules):
    (modules / "registry.json").write_text("{broken")
    with pytest.raises(RulesReadError):
        rules_page(modules)


def test_stress_test_names_read_as_words():
    assert [stress_test_name(s) for s in ("ST0", "ST5")] == ["Stress Test 0", "Stress Test 5"]


# --- Route: audited like every other reviewer page ---------------------------

@pytest.fixture
def client(modules):
    audit = InMemoryAuditTrail()
    app.dependency_overrides[get_modules_dir] = lambda: modules
    app.dependency_overrides[get_audit_trail] = lambda: audit
    yield TestClient(app), audit
    app.dependency_overrides.clear()


def test_opening_the_rules_page_is_audited_with_user_and_time(client):
    http, audit = client
    assert http.get("/rules-ui/modules", headers=REVIEWER).json()["modules"][0]["name"] == "Stress Test 0"
    assert http.get("/rules-ui/modules").status_code == 401
    events = audit.read_all()
    assert [(e.action, e.actor_id, e.outcome) for e in events] == [
        ("rules_viewed", "reviewer-7", "success"), ("rules_viewed", "unidentified", "blocked")]
    assert all(e.recorded_at.tzinfo is not None for e in events)


def test_an_unreadable_registry_answers_503_and_is_audited(client, modules):
    http, audit = client
    (modules / "registry.json").write_text("{broken")
    response = http.get("/rules-ui/modules", headers=REVIEWER)
    assert response.status_code == 503
    assert response.json()["detail"]["reason_code"] == "RULE_REGISTRY_UNREADABLE"
    assert audit.read_all()[0].reason_code == "RULE_REGISTRY_UNREADABLE"


def test_the_rules_page_is_served():
    http = TestClient(app)
    assert "Stress Test rules" in http.get("/rules/").text
    for asset in ("/rules/rules.js", "/rules/rules_logic.js", "/rules/rules.css"):
        assert http.get(asset).status_code == 200, asset
