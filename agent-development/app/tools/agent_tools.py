from __future__ import annotations

"""Private tools bound to specific sub agents."""

import re
from typing import Any


REQUEST_ID_PARAMETERS = {
    "type": "object",
    "properties": {
        "request_id": {
            "type": "string",
            "description": "Request id / 请求流水号，例如 REQ_001。",
        }
    },
    "required": ["request_id"],
}

QUERY_NODE_STATUS_PARAMETERS = {
    "type": "object",
    "properties": {
        "request_id": {
            "type": "string",
            "description": "Request id / 请求流水号，例如 REQ_001。",
        },
        "node_name": {
            "type": "string",
            "description": "流程节点名称，例如 signature_check、refund_callback。",
        },
    },
    "required": ["request_id"],
}

QUERY_INTERNAL_LOG_PARAMETERS = {
    "type": "object",
    "properties": {
        "request_id": {
            "type": "string",
            "description": "Request id / 请求流水号，例如 REQ_001。优先使用该字段查询日志。",
        },
        "query": {
            "type": "string",
            "description": "日志检索关键词。当没有 request_id 时使用，例如 E102、submitProposal、signature_check。",
        },
    },
    "required": [],
}

POLICY_NO_PARAMETERS = {
    "type": "object",
    "properties": {
        "policy_no": {
            "type": "string",
            "description": "保单号，例如 9201344266。",
        }
    },
    "required": ["policy_no"],
}

UPDATE_POLICY_STATUS_PARAMETERS = {
    "type": "object",
    "properties": {
        "policy_no": {
            "type": "string",
            "description": "保单号，例如 9201344266。",
        },
        "status": {
            "type": "string",
            "description": "目标保单状态，例如 active、suspended、cancelled。",
        },
    },
    "required": ["policy_no", "status"],
}

CLAIM_NO_PARAMETERS = {
    "type": "object",
    "properties": {
        "claim_no": {
            "type": "string",
            "description": "理赔号，例如 CLM001。",
        }
    },
    "required": ["claim_no"],
}

APPLY_SEQ_PARAMETERS = {
    "type": "object",
    "properties": {
        "apply_seq": {
            "type": "string",
            "description": "保全受理号 / 申请流水号，用于查询保全任务节点记录。",
        }
    },
    "required": ["apply_seq"],
}

ENDO_NOTICE_PARAMETERS = {
    "type": "object",
    "properties": {
        "apply_seq": {
            "type": "string",
            "description": "保全受理号。",
        },
        "policyNo": {
            "type": "string",
            "description": "保单号。",
        },
        "endorseType": {
            "type": "string",
            "description": "保全项。",
        },
    },
    "required": ["apply_seq", "policyNo", "endorseType"],
}

POLICY_RECOVERY_PARAMETERS = {
    "type": "object",
    "properties": {
        "handleType": {
            "type": "string",
            "description": "固定为 recovery。",
        },
        "premHandleFlag": {
            "type": "string",
            "description": "固定为 Y。",
        },
        "reqList": {
            "type": "array",
            "description": "保单恢复请求列表。",
            "items": {
                "type": "object",
                "properties": {
                    "policyInfo": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "policyNo": {
                                    "type": "string",
                                    "description": "保单号。",
                                }
                            },
                            "required": ["policyNo"],
                        },
                    }
                },
                "required": ["policyInfo"],
            },
        },
    },
    "required": ["handleType", "premHandleFlag", "reqList"],
}


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
    """Mock internal log query used by the troubleshooting MVP tool."""
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


async def query_policy_info(policy_no: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return {"found": bool(policy_no), "policy_no": policy_no, "product": "Enterprise Health Individual", "holder": "***"}


async def query_policy_status(policy_no: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return {"found": bool(policy_no), "policy_no": policy_no, "status": "active" if policy_no else "unknown"}


async def update_policy_status(policy_no: str | None = None, status: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return {"success": True, "policy_no": policy_no, "status": status or "updated"}


async def query_claim_case(claim_no: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return {"found": bool(claim_no), "claim_no": claim_no, "status": "processing"}


async def query_claim_progress(claim_no: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return {"found": bool(claim_no), "claim_no": claim_no, "progress": ["submitted", "reviewing"]}


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


async def notice_policy_update(apply_seq: str | None = None, policyNo: str | None = None, endorseType: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return await _mock_http_post(
        "/endo/notice/policy-update",
        {"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
    )


async def notice_customer_update(apply_seq: str | None = None, policyNo: str | None = None, endorseType: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return await _mock_http_post(
        "/endo/notice/customer-update",
        {"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
    )


async def notice_period_update(apply_seq: str | None = None, policyNo: str | None = None, endorseType: str | None = None, **kwargs: Any) -> dict[str, Any]:
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


async def notice_finance(apply_seq: str | None = None, policyNo: str | None = None, endorseType: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return await _mock_http_post(
        "/endo/notice/finance",
        {"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
    )


def register_agent_private_tools(registry) -> None:
    """Register MVP private tools."""
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="query_task_status",
        tool=query_task_status,
        description="根据 request_id 查询任务当前状态和当前节点，用于排查接口、保全、退保、回调等流程失败。",
        parameters=REQUEST_ID_PARAMETERS,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="query_node_status",
        tool=query_node_status,
        description="根据 request_id 和 node_name 查询指定流程节点状态。",
        parameters=QUERY_NODE_STATUS_PARAMETERS,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="query_internal_log",
        tool=query_internal_log,
        description="根据 request_id 或关键词查询内部日志，用于排查错误码、签名失败、回调失败、字段缺失等问题。",
        parameters=QUERY_INTERNAL_LOG_PARAMETERS,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="query_endo_task_record",
        tool=query_endo_task_record,
        description="查询保全任务记录表，获取任务详情和 9/10/11 节点状态。",
        parameters=APPLY_SEQ_PARAMETERS,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="notice_policy_update",
        tool=notice_policy_update,
        description="通知保全任务完成，保单更新失败，需要触发保单更新数据。",
        parameters=ENDO_NOTICE_PARAMETERS,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="notice_customer_update",
        tool=notice_customer_update,
        description="通知保全任务完成，客户更新失败，需要触发客户更新数据。",
        parameters=ENDO_NOTICE_PARAMETERS,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="notice_period_update",
        tool=notice_period_update,
        description="通知保全任务完成，账单/账期更新失败，需要触发账单更新数据。",
        parameters=ENDO_NOTICE_PARAMETERS,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="policy_suspendOrRecovery",
        tool=policy_suspendOrRecovery,
        description="保单恢复 / 保单解锁。用于 11 节点失败或未发短信场景，触发保单恢复和 E08 相关处理。",
        parameters=POLICY_RECOVERY_PARAMETERS,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="notice_finance",
        tool=notice_finance,
        description="通知保全任务完成，财务创单失败，需要触发财务创单并进行收退费。",
        parameters=ENDO_NOTICE_PARAMETERS,
    )
    registry.register_private(
        agent_name="policy_query_agent",
        name="query_policy_info",
        tool=query_policy_info,
        description="根据 policy_no 查询保单基础信息。",
        parameters=POLICY_NO_PARAMETERS,
    )
    registry.register_private(
        agent_name="policy_query_agent",
        name="query_policy_status",
        tool=query_policy_status,
        description="根据 policy_no 查询保单状态。",
        parameters=POLICY_NO_PARAMETERS,
    )
    registry.register_private(
        agent_name="policy_query_agent",
        name="update_policy_status",
        tool=update_policy_status,
        description=(
            "Update policy status by policy number. This is a write operation and requires human approval before "
            "execution."
        ),
        parameters=UPDATE_POLICY_STATUS_PARAMETERS,
        is_write=True,
    )
    registry.register_private(
        agent_name="claim_agent",
        name="query_claim_case",
        tool=query_claim_case,
        description="根据 claim_no 查询理赔案件基础信息。",
        parameters=CLAIM_NO_PARAMETERS,
    )
    registry.register_private(
        agent_name="claim_agent",
        name="query_claim_progress",
        tool=query_claim_progress,
        description="根据 claim_no 查询理赔进度。",
        parameters=CLAIM_NO_PARAMETERS,
    )
