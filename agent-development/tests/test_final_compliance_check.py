import pytest

from app.compliance.final_checker import FinalComplianceChecker
from app.runtime.graph import AgentGraphFactory
from app.schemas.compliance import FinalComplianceResult


@pytest.mark.asyncio
async def test_final_compliance_redacts_sensitive_values():
    result = await FinalComplianceChecker().check(
        "phone 13800138000 id 110101199003074233 bank 6222020202020202020 token=abc secret=xyz"
    )

    assert result.passed is True
    assert "13800138000" not in result.sanitized_answer
    assert "110101199003074233" not in result.sanitized_answer
    assert "6222020202020202020" not in result.sanitized_answer
    assert "token=abc" not in result.sanitized_answer
    assert "secret=xyz" not in result.sanitized_answer


@pytest.mark.asyncio
async def test_final_compliance_blocks_raw_tool_output():
    result = await FinalComplianceChecker().check("RAW_TOOL_RESULT {'token': 'abc', 'payload': 'internal'}")

    assert result.passed is False
    assert result.retry_required is True
    assert any(item.category == "raw_tool_output" for item in result.violations)


def test_compliance_route_retries_once_then_fallback():
    factory = object.__new__(AgentGraphFactory)
    failed = FinalComplianceResult(
        passed=False,
        sanitized_answer="RAW_TOOL_RESULT still unsafe",
        violations=[],
        risk_level="high",
        retry_required=True,
        fallback_answer="fallback",
    )

    assert factory.compliance_route({"final_compliance_result": failed.model_dump(), "retry_count": 0}) == "retry"
    assert factory.compliance_route({"final_compliance_result": failed.model_dump(), "retry_count": 1}) == "fallback"
