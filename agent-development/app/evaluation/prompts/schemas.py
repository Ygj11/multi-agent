from __future__ import annotations

"""Schemas for prompt evaluation fixtures."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PromptEvalCase(BaseModel):
    """One deterministic prompt evaluation case."""

    model_config = ConfigDict(extra="forbid")

    id: str
    description: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case(self) -> "PromptEvalCase":
        if not self.id.strip():
            raise ValueError("eval case id is required")
        if not self.expected:
            raise ValueError(f"eval case {self.id} must declare expected values")
        return self


class PromptEvalSuite(BaseModel):
    """A named collection of deterministic prompt eval cases."""

    model_config = ConfigDict(extra="forbid")

    suite: str
    scene: str
    cases: list[PromptEvalCase]

    @model_validator(mode="after")
    def validate_suite(self) -> "PromptEvalSuite":
        if not self.suite.strip():
            raise ValueError("eval suite name is required")
        if not self.scene.strip():
            raise ValueError(f"eval suite {self.suite} must declare scene")
        if not self.cases:
            raise ValueError(f"eval suite {self.suite} must include cases")
        ids = [case.id for case in self.cases]
        duplicate_ids = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
        if duplicate_ids:
            raise ValueError(f"eval suite {self.suite} has duplicate case ids: {duplicate_ids}")
        return self


class PromptEvalCaseResult(BaseModel):
    """Result for one fixture case."""

    id: str
    passed: bool
    reason: str = ""


class PromptEvalSuiteResult(BaseModel):
    """Result for one eval suite."""

    suite: str
    scene: str
    total: int
    passed: int
    failed: int
    cases: list[PromptEvalCaseResult]


class PromptEvalReport(BaseModel):
    """Aggregate eval runner output."""

    total: int
    passed: int
    failed: int
    suites: list[PromptEvalSuiteResult]

