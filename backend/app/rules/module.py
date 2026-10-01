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


class RuleExample(_Strict):
    """A short, fictional illustration of a rule for reviewers (Rules page,
    STORY-012). Display only: never sent to Claude (evaluation/prompt.py picks
    its fields by name), so adding or changing one does not change evaluations."""
    passes: str = Field(min_length=1, max_length=600)
    fails: str = Field(min_length=1, max_length=600)


class Rule(_Strict):
    id: str = Field(pattern=r"^ST[0-9]-[0-9]{3}$")
    check: str = Field(min_length=1)
    failure_feedback: str = Field(min_length=1)
    default_severity: Severity
    # How to apply the rule, where the spec's wording needs a decision.
    # Each note names its source (spec section or user decision).
    evaluation_notes: List[str] = []
    example: Optional[RuleExample] = None
    # Words that name this rule's part of a submission, matched in a label
    # such as "Dataset Screenshot:" (lowercase). They tell which rule's part
    # an image sits under (evaluation/image_selection.py).
    part_keywords: List[str] = []
    # Claude is shown images only for a rule that needs them, and only images
    # in that rule's part (user decision 2026-10-02). Needs part_keywords.
    needs_image: bool = False

    @model_validator(mode="after")
    def _image_rule_has_a_part(self) -> "Rule":
        if self.needs_image and not self.part_keywords:
            raise ValueError(f"{self.id} needs_image but has no part_keywords")
        if any(not word.strip() or word != word.strip().lower() for word in self.part_keywords):
            raise ValueError(f"{self.id} part_keywords must be non-empty, trimmed and lowercase")
        return self


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
