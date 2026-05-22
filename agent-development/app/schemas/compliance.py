from __future__ import annotations

"""Final outbound compliance check schemas."""

from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high"]


class ComplianceViolation(BaseModel):
    """One outbound response compliance violation."""

    category: str
    severity: RiskLevel
    message: str


class FinalComplianceResult(BaseModel):
    """Main-agent final compliance check result."""

    passed: bool
    sanitized_answer: str
    violations: list[ComplianceViolation] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    retry_required: bool = False
    fallback_answer: str = "当前回复包含不适合直接外发的信息，我已拦截原始内容。请补充更具体的业务问题，我会在不暴露敏感信息的前提下重新说明。"
