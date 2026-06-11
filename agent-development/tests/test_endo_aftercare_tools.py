import pytest

from app.tools.agent_tools import (
    notice_finance,
    notice_policy_update,
    policy_suspendOrRecovery,
    query_endo_task_record,
)


def _record(result, task_type: str):
    return next(item for item in result["records"] if item["task_type"] == task_type)


@pytest.mark.asyncio
async def test_query_endo_task_record_policy_update_fail():
    result = await query_endo_task_record(apply_seq="APPLY_POLICY_UPDATE_FAIL")

    assert _record(result, "9")["task_status"] == "E"
    assert "保单更新错误" in _record(result, "9")["response_body"]


@pytest.mark.asyncio
async def test_query_endo_task_record_realistic_apply_seq_defaults_to_policy_update_fail():
    result = await query_endo_task_record(apply_seq="930123456789012")

    assert result["mock"] is True
    assert result["mock_skill_id"] == "troubleshooting_agent.endo_completion_aftercare"
    assert result["mock_case"] == "policy_update_fail"
    assert _record(result, "9")["task_status"] == "E"
    assert "保单更新错误" in _record(result, "9")["response_body"]


@pytest.mark.asyncio
async def test_query_endo_task_record_customer_update_fail():
    result = await query_endo_task_record(apply_seq="APPLY_CUSTOMER_UPDATE_FAIL")

    assert _record(result, "9")["task_status"] == "E"
    assert "调用新客户接口异常" in _record(result, "9")["response_body"]


@pytest.mark.asyncio
async def test_query_endo_task_record_period_update_fail():
    result = await query_endo_task_record(apply_seq="APPLY_PERIOD_UPDATE_FAIL")

    assert _record(result, "9")["task_status"] == "E"
    assert "账单更新异常，失败" in _record(result, "9")["response_body"]


@pytest.mark.asyncio
async def test_query_endo_task_record_unlock_fail():
    result = await query_endo_task_record(apply_seq="APPLY_UNLOCK_FAIL")

    assert _record(result, "11")["task_status"] == "E"


@pytest.mark.asyncio
async def test_query_endo_task_record_finance_fail():
    result = await query_endo_task_record(apply_seq="APPLY_FINANCE_FAIL")

    assert _record(result, "10")["task_status"] == "E"


@pytest.mark.asyncio
async def test_endo_notice_tools_return_mock_http_response():
    notice = await notice_policy_update(apply_seq="APPLY_1", policyNo="P001", endorseType="退保")
    finance = await notice_finance(apply_seq="APPLY_1", policyNo="P001", endorseType="退保")
    recovery = await policy_suspendOrRecovery(
        handleType="recovery",
        premHandleFlag="Y",
        reqList=[{"policyInfo": [{"policyNo": "P001"}]}],
    )

    assert notice["mock"] is True
    assert finance["success"] is True
    assert recovery["payload"]["handleType"] == "recovery"
