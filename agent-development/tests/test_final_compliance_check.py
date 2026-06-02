import pytest

from app.runtime.graph import AgentGraphFactory
from app.verification.schemas import VerificationInput, VerificationResult
from app.verification.verifiers.compliance_verifier import ComplianceVerifier


@pytest.mark.asyncio
async def test_final_compliance_redacts_sensitive_values():
    result = await ComplianceVerifier().verify(
        VerificationInput(
            stage="pre_answer",
            answer="phone 13800138000 id 110101199003074233 bank 6222020202020202020 token=abc secret=xyz",
        )
    )

    assert result.passed is True
    assert result.action == "patch"
    assert "13800138000" not in result.patched_output
    assert "110101199003074233" not in result.patched_output
    assert "6222020202020202020" not in result.patched_output
    assert "token=abc" not in result.patched_output
    assert "secret=xyz" not in result.patched_output


@pytest.mark.asyncio
async def test_final_compliance_blocks_raw_tool_output():
    result = await ComplianceVerifier().verify(
        VerificationInput(stage="pre_answer", answer="RAW_TOOL_RESULT {'token': 'abc', 'payload': 'internal'}")
    )

    assert result.passed is False
    assert result.action == "retry"
    assert result.code == "compliance_violation"
    assert any(item["category"] == "raw_tool_output" for item in result.redactions)


def test_verification_route_retries_once_then_fallback():
    factory = object.__new__(AgentGraphFactory)
    failed = VerificationResult(
        passed=False,
        stage="pre_answer",
        verifier_name="compliance",
        severity="blocking",
        action="retry",
        code="compliance_violation",
    )

    assert factory.compliance_route({"pre_answer_verification_result": failed.model_dump(), "retry_count": 0}) == "retry"
    assert factory.compliance_route({"pre_answer_verification_result": failed.model_dump(), "retry_count": 1}) == "fallback"
