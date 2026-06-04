import pytest

from app.auth.principal import Principal
from app.verification.field_visibility_policy import FieldVisibilityPolicy
from app.verification.schemas import VerificationInput
from app.verification.verifiers.data_permission_verifier import DataPermissionVerifier


def test_field_visibility_policy_loads_config_file():
    policy = FieldVisibilityPolicy.load()

    assert "data_admin" in policy.privileged_roles
    assert policy.rule("phone_number").mask == "***PHONE***"
    assert "病史" in policy.rule("health_privacy").keywords
    assert policy.rule("bank_card").preserve_if_category_allowed == "id_card"


def test_field_visibility_policy_permission_check_uses_configured_permissions():
    policy = FieldVisibilityPolicy.from_mapping(
        {
            "privileged_roles": ["supervisor"],
            "categories": {
                "member_number": {
                    "action": "redact",
                    "pattern": "M\\d+",
                    "mask": "***MEMBER***",
                    "allow_permissions": ["member.read"],
                }
            },
        }
    )

    assert policy.can_view(category="member_number", roles=set(), permissions={"member.read"})
    assert policy.can_view(category="member_number", roles={"supervisor"}, permissions=set())
    assert not policy.can_view(category="member_number", roles=set(), permissions=set())


def test_field_visibility_policy_missing_file_fails_clearly(tmp_path):
    missing_path = tmp_path / "missing_policy.yaml"

    with pytest.raises(FileNotFoundError, match="field visibility policy not found"):
        FieldVisibilityPolicy.load(missing_path)


@pytest.mark.asyncio
async def test_data_permission_verifier_uses_custom_policy_without_code_change():
    policy = FieldVisibilityPolicy.from_mapping(
        {
            "categories": {
                "member_number": {
                    "action": "redact",
                    "pattern": "M\\d{4}",
                    "mask": "***MEMBER***",
                    "allow_permissions": ["member.sensitive.read"],
                }
            }
        }
    )
    verifier = DataPermissionVerifier(policy=policy)

    denied = await verifier.verify(
        VerificationInput(
            stage="pre_answer",
            answer="会员号 M1234",
            principal=Principal(tenant_id="t1", subject="u1").model_dump(),
        )
    )
    assert denied.action == "patch"
    assert denied.patched_output == "会员号 ***MEMBER***"

    allowed = await verifier.verify(
        VerificationInput(
            stage="pre_answer",
            answer="会员号 M1234",
            principal=Principal(
                tenant_id="t1",
                subject="u1",
                data_permissions=["member.sensitive.read"],
            ).model_dump(),
        )
    )
    assert allowed.action == "allow"
    assert allowed.redactions == []


@pytest.mark.asyncio
async def test_data_permission_verifier_preserves_allowed_id_card_from_bank_card_rule():
    verifier = DataPermissionVerifier()

    result = await verifier.verify(
        VerificationInput(
            stage="pre_answer",
            answer="身份证 110101199003074233 银行卡 6222020202020202020",
            principal=Principal(
                tenant_id="t1",
                subject="u1",
                data_permissions=["pii.id_card.read"],
            ).model_dump(),
        )
    )

    assert result.action == "patch"
    assert "110101199003074233" in result.patched_output
    assert "6222020202020202020" not in result.patched_output
    assert "***BANK_CARD***" in result.patched_output
