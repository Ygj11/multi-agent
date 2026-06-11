from __future__ import annotations

"""MVP local business tool handlers.

These handlers are deterministic local stand-ins for insurance core systems,
workflow systems, and internal log APIs. They are intentionally separated from
ToolDefinition registration so production wiring can replace them without
changing AgentGraph, ToolExecutor, or LLMProvider.
"""

import re
from typing import Any


MVP_LOCAL_TOOL_HANDLERS = True
ENDO_AFTERCARE_MOCK_SKILL_ID = "troubleshooting_agent.endo_completion_aftercare"
REALISTIC_APPLY_SEQ_PATTERN = re.compile(r"^930\d{12}$", re.IGNORECASE)


def _base_endo_records() -> list[dict[str, str]]:
    return [
        {"task_type": "9", "task_status": "S", "response_body": "更新保单、客户、账期成功"},
        {"task_type": "10", "task_status": "S", "response_body": "财务创单成功"},
        {"task_type": "11", "task_status": "S", "response_body": "保单恢复成功，E08消息发送成功"},
    ]


def _resolve_endo_mock_case(apply_seq: str | None, mock_case: str | None, kwargs: dict[str, Any]) -> str:
    explicit = str(mock_case or kwargs.get("mock_case") or "").upper()
    if explicit:
        return explicit

    hint_text = " ".join(str(value) for value in kwargs.values() if value is not None)
    if any(token in hint_text for token in ("客户", "新客户")):
        return "CUSTOMER_UPDATE_FAIL"
    if any(token in hint_text for token in ("账单", "账期")):
        return "PERIOD_UPDATE_FAIL"
    if any(token in hint_text for token in ("解锁", "短信", "E08")):
        return "UNLOCK_FAIL"
    if any(token in hint_text for token in ("财务", "退费", "收退费")):
        return "FINANCE_FAIL"
    if any(token in hint_text for token in ("保单未更新", "没有更新", "更新失败", "保单更新")):
        return "POLICY_UPDATE_FAIL"

    normalized_apply_seq = str(apply_seq or "").strip()
    if REALISTIC_APPLY_SEQ_PATTERN.fullmatch(normalized_apply_seq):
        return "POLICY_UPDATE_FAIL"
    return normalized_apply_seq.upper()


async def _mock_http_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "mock": True,
        "mock_skill_id": ENDO_AFTERCARE_MOCK_SKILL_ID,
        "url": url,
        "payload": payload,
        "success": True,
        "message": "mocked endo aftercare response for LLM tool-calling test",
    }


async def query_task_status(request_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return {"request_id": request_id, "status": "failed" if request_id else "unknown", "current_node": "signature_check"}


async def query_node_status(request_id: str | None = None, node_name: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return {"request_id": request_id, "node_name": node_name or "signature_check", "status": "error"}


async def query_internal_log(request_id: str | None = None, query: str | None = None, **kwargs: Any) -> dict[str, Any]:
    resolved_request_id = request_id or _extract_request_id(query or "")
    mock_logs: dict[str, dict[str, Any]] = {
        "REQ_001": {
            "found": True,
            "request_id": "REQ_001",
            "channel": "XX_CHANNEL",
            "product_code": "ESHENGBAO",
            "interface_name": "submitProposal",
            "error_code": "E102",
            "error_message": "signature verification failed",
            "server_sign": "B82D****",
            "partner_sign": "A9F3****",
            "signature_rule_version": "v2",
            "suspected_reason": "partner signature does not include timestamp",
        },
        "REQ_002": {
            "found": True,
            "request_id": "REQ_002",
            "channel": "XX_CHANNEL",
            "product_code": "ESHENGBAO",
            "interface_name": "submitProposal",
            "error_code": "E102",
            "error_message": "signature verification failed",
            "server_sign": "C72E****",
            "partner_sign": "C72E****",
            "signature_rule_version": "v2",
            "suspected_reason": "timestamp expired",
        },
    }
    if resolved_request_id in mock_logs:
        return mock_logs[resolved_request_id]
    return {"found": False, "message": "No mock internal log found for this requestId."}


def _extract_request_id(text: str) -> str | None:
    match = re.search(r"\bREQ_\d+\b", text)
    return match.group(0) if match else None


async def query_endo_task_record(apply_seq: str | None = None, mock_case: str | None = None, **kwargs: Any) -> dict[str, Any]:
    case = _resolve_endo_mock_case(apply_seq, mock_case, kwargs)
    records = _base_endo_records()
    scenario = "all_success"
    if "POLICY_UPDATE_FAIL" in case:
        records[0] = {"task_type": "9", "task_status": "E", "response_body": "保单更新错误：mock policy update failed"}
        scenario = "policy_update_fail"
    elif "CUSTOMER_UPDATE_FAIL" in case:
        records[0] = {"task_type": "9", "task_status": "E", "response_body": "调用新客户接口异常：mock customer update failed"}
        scenario = "customer_update_fail"
    elif "PERIOD_UPDATE_FAIL" in case:
        records[0] = {"task_type": "9", "task_status": "E", "response_body": "账单更新异常，失败：mock period update failed"}
        scenario = "period_update_fail"
    elif "UNLOCK_FAIL" in case:
        records[2] = {"task_type": "11", "task_status": "E", "response_body": "保单恢复失败，E08消息未发送"}
        scenario = "unlock_fail"
    elif "FINANCE_FAIL" in case:
        records[1] = {"task_type": "10", "task_status": "E", "response_body": "财务创单失败，未发起收退费"}
        scenario = "finance_fail"
    return {
        "apply_seq": apply_seq,
        "records": records,
        "success": True,
        "mock": True,
        "mock_skill_id": ENDO_AFTERCARE_MOCK_SKILL_ID,
        "mock_case": scenario,
    }


async def notice_policy_update(
    apply_seq: str | None = None,
    policyNo: str | None = None,
    endorseType: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return await _mock_http_post(
        "/endo/notice/policy-update",
        {"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
    )


async def notice_customer_update(
    apply_seq: str | None = None,
    policyNo: str | None = None,
    endorseType: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return await _mock_http_post(
        "/endo/notice/customer-update",
        {"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
    )


async def notice_period_update(
    apply_seq: str | None = None,
    policyNo: str | None = None,
    endorseType: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return await _mock_http_post(
        "/endo/notice/period-update",
        {"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
    )


async def policy_suspendOrRecovery(
    handleType: str | None = None,
    premHandleFlag: str | None = None,
    reqList: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return await _mock_http_post(
        "/policy/suspendOrRecovery",
        {"handleType": handleType, "premHandleFlag": premHandleFlag, "reqList": reqList or []},
    )


async def notice_finance(
    apply_seq: str | None = None,
    policyNo: str | None = None,
    endorseType: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return await _mock_http_post(
        "/endo/notice/finance",
        {"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
    )
