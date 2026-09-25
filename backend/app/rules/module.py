"""Rule module contract (STORY-003: REQ-003; points at REQ-017).

A rule module is versioned configuration, not code: one JSON file per
Stress Test and version, e.g. rules/modules/ST0/v1.json. Adding ST1 later
means adding a file, not changing the application.

RuleModule validates a module's shape when it is parsed, so a broken or
mixed-up file fails loudly instead of being applied:
- every rule id belongs to the module's own Stress Test (an ST0 module can
  never carry an ST1 rule), and ids are unique;
- every rule sits in exactly one stage, and stages only name known rules;
- stages are numbered 1..n in order, and an advisory stage never blocks.
Unknown fields are rejected, so a typo cannot silently drop a setting.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

StressTestId = Field(pattern=r"^ST[0-9]$")
Severity = Literal["Required Fix", "Needs Attention", "Improvement"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rule(_Strict):
    id: str = Field(pattern=r"^ST[0-9]-[0-9]{3}$")
    check: str = Field(min_length=1)
    failure_feedback: str = Field(min_length=1)
    default_severity: Severity
    # How to apply the rule, where the spec's wording needs a decision.
    # Each note names its source (spec section or user decision).
    evaluation_notes: List[str] = []


class Stage(_Strict):
    number: int = Field(ge=1)
    name: str = Field(min_length=1)
    kind: Literal["structural", "artifact", "advisory"]
    blocking: bool
    rule_ids: List[str] = []
    instructions: List[str] = []


class ReviewerNote(_Strict):
    """Something to tell the human reviewer. Never a rule failure.
    student_feedback, when set, is wording the reviewer can pass on."""
    id: str = Field(pattern=r"^[A-Z_]+$")
    when: str = Field(min_length=1)
    note: str = Field(min_length=1)
    student_feedback: Optional[str] = None
    source: str = Field(min_length=1)


class ProblemCount(_Strict):
    min: int = Field(ge=1)
    max: int = Field(ge=1)


class RuleModule(_Strict):
    stress_test_id: str = StressTestId
    version: str = Field(pattern=r"^v[0-9]+$")
    source_document: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    out_of_scope: List[str]
    rules: List[Rule] = Field(min_length=1)
    stages: List[Stage] = Field(min_length=1)
    required_problem_fields: List[str] = []
    problem_count: ProblemCount
    tolerance: List[str] = []
    advisory_guidance: List[str] = []
    reviewer_notes: List[ReviewerNote] = []
    guardrails: List[str] = []

    @model_validator(mode="after")
    def _consistent(self) -> "RuleModule":
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        foreign = [rule_id for rule_id in ids if not rule_id.startswith(f"{self.stress_test_id}-")]
        if foreign:
            raise ValueError(f"rules {foreign} do not belong to {self.stress_test_id}")

        if [stage.number for stage in self.stages] != list(range(1, len(self.stages) + 1)):
            raise ValueError("stages must be numbered 1..n in order")
        staged = [rule_id for stage in self.stages for rule_id in stage.rule_ids]
        unknown = sorted(set(staged) - set(ids))
        if unknown:
            raise ValueError(f"stages name unknown rules {unknown}")
        if sorted(staged) != sorted(ids):
            raise ValueError("every rule must sit in exactly one stage")
        if any(stage.kind == "advisory" and stage.blocking for stage in self.stages):
            raise ValueError("an advisory stage must not block")

        if self.problem_count.min > self.problem_count.max:
            raise ValueError("problem_count.min is greater than problem_count.max")
        return self

    def rule(self, rule_id: str) -> Rule:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise KeyError(rule_id)
