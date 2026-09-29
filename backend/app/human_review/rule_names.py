"""Readable rule names for the reviewer page (STORY-005): "ST0-002" is shown
as its check, e.g. "At least one valid public dataset source link is present".

Reads the exact module version the draft was evaluated with
(rules/modules/<ST>/<version>.json), so a later rule version cannot relabel an
older draft. Read-only and not audited: it is display text, not a rule load
(rules.loader.load_rules is the audited path used for evaluation).

Fallback: if the module cannot be read or is invalid, an empty mapping is
returned and a warning is logged; the page then shows the rule codes. A
missing label must never stop a reviewer from working.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from pydantic import ValidationError

from app.rules.loader import MODULES_DIR
from app.rules.module import RuleModule

logger = logging.getLogger("stress_test_review.human_review")


def rule_names(stress_test_id: str, rule_version: str, modules_dir: Path = MODULES_DIR) -> Dict[str, str]:
    # Both ids are validated by EvaluationResult (^ST[0-9]$, ^v[0-9]+$), so
    # they cannot walk outside the modules folder.
    path = Path(modules_dir) / stress_test_id / f"{rule_version}.json"
    try:
        module = RuleModule.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        logger.warning(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(), "level": "warn", "service": "backend",
            "event": "rule_names_unavailable", "outcome": "partial", "error_class": type(exc).__name__,
            "stress_test_id": stress_test_id, "rule_version": rule_version,
        }))
        return {}
    return {rule.id: rule.check for rule in module.rules}
