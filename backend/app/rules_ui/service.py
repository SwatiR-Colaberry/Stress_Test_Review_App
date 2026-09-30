"""Build the Rules page from the rule files (STORY-012). Read-only.

Reads registry.json for the active version of each Stress Test, then each
module file, validated by RuleModule exactly as evaluation does. This is
display, not a rule load: evaluation keeps using rules.loader.load_rules
(audited as rules_loaded); the page view itself is audited by the route.

Failure modes: registry missing, unreadable or invalid -> RulesReadError
(RULE_REGISTRY_UNREADABLE, 503: nothing trustworthy to show). One module
missing / invalid / naming another Stress Test or version -> that module is
shown as unavailable with RULE_MODULE_NOT_FOUND / RULE_MODULE_INVALID /
RULE_VERSION_MISMATCH, and the others are still shown. Local files only, so
no timeout or retry: a read either works at once or fails with OSError.
"""
from pathlib import Path

from pydantic import ValidationError

from app.rules.loader import MODULES_DIR, RuleRegistry
from app.rules.module import RuleModule
from app.rules_ui.models import ModuleView, RulesPage, StageView


class RulesReadError(Exception):
    error_class = "RulesReadError"
    reason_code = "RULE_REGISTRY_UNREADABLE"


def stress_test_name(stress_test_id: str) -> str:
    """"ST0" -> "Stress Test 0" (headings use words, user request 2026-09-30)."""
    return f"Stress Test {int(stress_test_id[2:])}"


def rules_page(modules_dir: Path = MODULES_DIR) -> RulesPage:
    try:
        registry = RuleRegistry.model_validate_json((Path(modules_dir) / "registry.json").read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise RulesReadError(f"rule registry unreadable: {type(exc).__name__}") from exc
    entries = sorted(registry.root.items(), key=lambda item: int(item[0][2:]))
    return RulesPage(modules=[_module(st, version, Path(modules_dir)) for st, version in entries])


def _module(stress_test_id: str, version: str, modules_dir: Path) -> ModuleView:
    unavailable = dict(stress_test_id=stress_test_id, name=stress_test_name(stress_test_id), version=version,
                       available=False)
    try:
        text = (modules_dir / stress_test_id / f"{version}.json").read_text(encoding="utf-8")
    except OSError:
        return ModuleView(**unavailable, reason_code="RULE_MODULE_NOT_FOUND")
    try:
        module = RuleModule.model_validate_json(text)
    except ValidationError:
        return ModuleView(**unavailable, reason_code="RULE_MODULE_INVALID")
    if (module.stress_test_id, module.version) != (stress_test_id, version):
        return ModuleView(**unavailable, reason_code="RULE_VERSION_MISMATCH")
    return ModuleView(
        stress_test_id=stress_test_id, name=stress_test_name(stress_test_id), version=version, available=True,
        purpose=module.purpose, out_of_scope=module.out_of_scope,
        required_problem_fields=module.required_problem_fields, problem_count=module.problem_count,
        tolerance=module.tolerance, advisory_guidance=module.advisory_guidance,
        reviewer_notes=module.reviewer_notes,
        stages=[StageView(number=s.number, name=s.name, kind=s.kind, blocking=s.blocking,
                          instructions=s.instructions,
                          rules=[r for r in module.rules if r.id in s.rule_ids]) for s in module.stages],
    )
