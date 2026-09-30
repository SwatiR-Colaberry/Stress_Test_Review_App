"""What the Rules page is sent (STORY-012): every active Stress Test rule
module, grouped by stage, in words a reviewer can use. Built from the rule
files themselves, so ST1-ST5 appear once their module and registry line are
added (REQ-017), with no page change.
"""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.rules.module import ProblemCount, ReviewerNote, Rule


class StageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    name: str
    kind: str
    blocking: bool
    instructions: List[str] = []
    rules: List[Rule]  # in the module's order


class ModuleView(BaseModel):
    """One Stress Test's rules. available=False (with reason_code) when its
    file cannot be read or is invalid; the other modules are still shown."""
    model_config = ConfigDict(extra="forbid")

    stress_test_id: str
    name: str  # "Stress Test 0"
    version: str
    available: bool
    reason_code: Optional[str] = None
    purpose: Optional[str] = None
    out_of_scope: List[str] = []
    required_problem_fields: List[str] = []
    problem_count: Optional[ProblemCount] = None
    tolerance: List[str] = []
    advisory_guidance: List[str] = []
    reviewer_notes: List[ReviewerNote] = []
    stages: List[StageView] = []


class RulesPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modules: List[ModuleView]
