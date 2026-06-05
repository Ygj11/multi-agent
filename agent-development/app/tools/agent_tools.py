from __future__ import annotations

"""Private tools bound to specific sub agents.

The functions in this module are MVP local handlers. They are registered into
ToolRegistry to exercise the enterprise harness path locally; external
production integrations should replace these handlers behind the same
ToolDefinition contract instead of changing AgentGraph or LLMProvider.
"""

from app.integrations.pos_api_client import PosAPIClient
from app.tools.handlers.mvp_agent_tool_handlers import (
    MVP_LOCAL_TOOL_HANDLERS,
    notice_customer_update,
    notice_finance,
    notice_period_update,
    notice_policy_update,
    policy_suspendOrRecovery,
    query_claim_case,
    query_claim_progress,
    query_endo_task_record,
    query_internal_log,
    query_node_status,
    query_policy_info,
    query_policy_status,
    query_task_status,
    update_policy_status,
)
from app.tools.handlers.pos_query_tool_handlers import (
    build_pos_calc_surrender_premium_tool,
    build_pos_query_approval_text_tool,
    build_pos_query_available_items_tool,
    build_pos_query_policy_standard_tool,
    build_pos_submit_verify_tool,
)


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

POS_QUERY_AVAILABLE_ITEMS_PARAMETERS = {
    "type": "object",
    "properties": {
        "policyNo": {"type": "string", "description": "保单号。"},
        "customerNo": {"type": "string", "description": "保单上的客户号。"},
        "src": {"type": "integer", "description": "来源，默认 16。"},
    },
    "required": ["policyNo", "customerNo"],
}

POS_CALC_SURRENDER_PREMIUM_PARAMETERS = {
    "type": "object",
    "properties": {
        "applyDate": {"type": "integer", "description": "受理日期毫秒时间戳。"},
        "policyNo": {"type": "string", "description": "保单号。"},
        "endorseType": {"type": "string", "description": "保全项，默认 001028。"},
        "taskSrc": {"type": "string", "description": "任务来源，默认 01。"},
        "surrenderType": {"type": "string", "description": "退保类型，默认 1。"},
        "surDate": {"type": "integer", "description": "退保日期毫秒时间戳。"},
        "commission": {"type": "string", "description": "佣金标识，默认 1。"},
        "operatorId": {"type": "string", "description": "操作人，优先从 Principal.user_id 获取。"},
    },
    "required": ["applyDate", "policyNo", "surDate"],
}

POS_QUERY_POLICY_STANDARD_PARAMETERS = {
    "type": "object",
    "properties": {
        "policyNo": {"type": "string", "description": "保单号，工具内部映射为接口字段 polNo。"},
        "withInsureds": {"type": "string", "description": "是否携带被保人信息，默认 Y。"},
        "extensions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "扩展信息，默认 pollist、assuredPolicyInfo、pollLock。",
        },
    },
    "required": ["policyNo"],
}

POS_QUERY_APPROVAL_TEXT_PARAMETERS = {
    "type": "object",
    "properties": {
        "applySeq": {"type": "string", "description": "保全受理号 / 申请流水号。"},
        "pageSize": {"type": "integer", "description": "分页大小，默认 0。"},
        "pageNo": {"type": "integer", "description": "页码，默认 1。"},
        "operatorId": {"type": "string", "description": "操作人，优先从 Principal.user_id 获取。"},
    },
    "required": ["applySeq"],
}

POS_SUBMIT_VERIFY_PARAMETERS = {
    "type": "object",
    "properties": {
        "policyNo": {"type": "string", "description": "保单号。"},
        "endorseType": {"type": "string", "description": "保全项，默认 001028。"},
        "payMode": {"type": "string", "description": "支付方式，默认 Y。"},
        "acceptDate": {"type": "integer", "description": "受理日期毫秒时间戳。"},
        "surrenderReason": {"type": "string", "description": "退费原因，默认 11。"},
        "taskSrc": {"type": "string", "description": "任务来源，默认 31。"},
        "operatorId": {"type": "string", "description": "操作人，优先从 Principal.user_id 获取。"},
    },
    "required": ["policyNo", "acceptDate"],
}

def register_agent_private_tools(registry, pos_api_client: PosAPIClient | None = None) -> None:
    """Register MVP private tools."""
    pos_api_client = pos_api_client or PosAPIClient(base_url=None, enabled=False)
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
        is_write=True,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="notice_customer_update",
        tool=notice_customer_update,
        description="通知保全任务完成，客户更新失败，需要触发客户更新数据。",
        parameters=ENDO_NOTICE_PARAMETERS,
        is_write=True,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="notice_period_update",
        tool=notice_period_update,
        description="通知保全任务完成，账单/账期更新失败，需要触发账单更新数据。",
        parameters=ENDO_NOTICE_PARAMETERS,
        is_write=True,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="policy_suspendOrRecovery",
        tool=policy_suspendOrRecovery,
        description="保单恢复 / 保单解锁。用于 11 节点失败或未发短信场景，触发保单恢复和 E08 相关处理。",
        parameters=POLICY_RECOVERY_PARAMETERS,
        is_write=True,
    )
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="notice_finance",
        tool=notice_finance,
        description="通知保全任务完成，财务创单失败，需要触发财务创单并进行收退费。",
        parameters=ENDO_NOTICE_PARAMETERS,
        is_write=True,
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
    registry.register_private(
        agent_name="pos_query_agent",
        name="pos_query_available_items",
        tool=build_pos_query_available_items_tool(pos_api_client),
        description="查询保单线上可做保全项。",
        parameters=POS_QUERY_AVAILABLE_ITEMS_PARAMETERS,
        operation="read",
    )
    registry.register_private(
        agent_name="pos_query_agent",
        name="pos_calc_surrender_premium",
        tool=build_pos_calc_surrender_premium_tool(pos_api_client),
        description="查询退保试算详情，包括退保金额和试算相关结果。",
        parameters=POS_CALC_SURRENDER_PREMIUM_PARAMETERS,
        operation="read",
    )
    registry.register_private(
        agent_name="pos_query_agent",
        name="pos_query_policy_standard",
        tool=build_pos_query_policy_standard_tool(pos_api_client),
        description="查询保全保单标准信息，包含保单、被保人和锁定扩展信息。",
        parameters=POS_QUERY_POLICY_STANDARD_PARAMETERS,
        operation="read",
    )
    registry.register_private(
        agent_name="pos_query_agent",
        name="pos_query_approval_text",
        tool=build_pos_query_approval_text_tool(pos_api_client),
        description="通过受理号查询保全批文和变更详情。",
        parameters=POS_QUERY_APPROVAL_TEXT_PARAMETERS,
        operation="read",
    )
    registry.register_private(
        agent_name="pos_query_agent",
        name="pos_submit_verify",
        tool=build_pos_submit_verify_tool(pos_api_client),
        description="执行保全任务提交前校验，例如退保提交校验和支付方式校验。",
        parameters=POS_SUBMIT_VERIFY_PARAMETERS,
        operation="read",
    )
