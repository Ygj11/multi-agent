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


async def _mock_http_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "mock": True,
        "url": url,
        "payload": payload,
        "success": True,
        "message": "mocked http response",
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
    case = (mock_case or apply_seq or "").upper()
    records = [
        {"task_type": "9", "task_status": "S", "response_body": "更新保单、客户、账期成功"},
        {"task_type": "10", "task_status": "S", "response_body": "财务创单成功"},
        {"task_type": "11", "task_status": "S", "response_body": "保单恢复成功，E08消息发送成功"},
    ]
    if "POLICY_UPDATE_FAIL" in case:
        records[0] = {"task_type": "9", "task_status": "E", "response_body": "保单更新错误：mock policy update failed"}
    elif "CUSTOMER_UPDATE_FAIL" in case:
        records[0] = {"task_type": "9", "task_status": "E", "response_body": "调用新客户接口异常：mock customer update failed"}
    elif "PERIOD_UPDATE_FAIL" in case:
        records[0] = {"task_type": "9", "task_status": "E", "response_body": "账单更新异常，失败：mock period update failed"}
    elif "UNLOCK_FAIL" in case:
        records[2] = {"task_type": "11", "task_status": "E", "response_body": "保单恢复失败，E08消息未发送"}
    elif "FINANCE_FAIL" in case:
        records[1] = {"task_type": "10", "task_status": "E", "response_body": "财务创单失败，未发起收退费"}
    return {"apply_seq": apply_seq, "records": records, "success": True}


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
