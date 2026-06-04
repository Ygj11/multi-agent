import pytest

from app.runtime.graph import AgentGraphFactory
from app.auth.principal import Principal
from app.verification.schemas import VerificationInput, VerificationResult
from app.verification.service import VerificationService
from app.verification.verifiers.compliance_verifier import ComplianceVerifier
from app.verification.verifiers.data_permission_verifier import DataPermissionVerifier


@pytest.mark.asyncio
async def test_pre_answer_verification_redacts_pii_by_principal_and_credentials_always():
    service = VerificationService([DataPermissionVerifier(), ComplianceVerifier()])

    result = await service.verify(
        VerificationInput(
            stage="pre_answer",
            answer="phone 13800138000 id 110101199003074233 bank 6222020202020202020 token=abc secret=xyz",
            principal=Principal(tenant_id="t1", subject="u1").model_dump(),
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
async def test_pre_answer_verification_allows_pii_for_privileged_principal_but_redacts_credentials():
    service = VerificationService([DataPermissionVerifier(), ComplianceVerifier()])

    result = await service.verify(
        VerificationInput(
            stage="pre_answer",
            answer="phone 13800138000 id 110101199003074233 token=abc",
            principal=Principal(
                tenant_id="t1",
                subject="u1",
                data_permissions=["pii.phone.read", "pii.id_card.read"],
            ).model_dump(),
        )
    )

    assert result.action == "patch"
    assert "13800138000" in result.patched_output
    assert "110101199003074233" in result.patched_output
    assert "token=abc" not in result.patched_output
    assert "token=***" in result.patched_output


@pytest.mark.asyncio
async def test_compliance_verifier_only_handles_absolute_outbound_secrets():
    result = await ComplianceVerifier().verify(
        VerificationInput(stage="pre_answer", answer="phone 13800138000 token=abc secret=xyz")
    )

    assert result.action == "patch"
    assert "13800138000" in result.patched_output
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
