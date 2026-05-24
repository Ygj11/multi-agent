from __future__ import annotations

"""Private tools bound to specific sub agents."""

from typing import Any

from app.tools.builtin_tools import query_internal_log


async def query_task_status(request_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return {"request_id": request_id, "status": "failed" if request_id else "unknown", "current_node": "signature_check"}


async def query_node_status(request_id: str | None = None, node_name: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return {"request_id": request_id, "node_name": node_name or "signature_check", "status": "error"}


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


def register_agent_private_tools(registry) -> None:
    """Register MVP private tools."""
    registry.register_private(agent_name="troubleshooting_agent", name="query_task_status", tool=query_task_status)
    registry.register_private(agent_name="troubleshooting_agent", name="query_node_status", tool=query_node_status)
    registry.register_private(agent_name="troubleshooting_agent", name="query_internal_log", tool=query_internal_log)
    registry.register_private(agent_name="policy_query_agent", name="query_policy_info", tool=query_policy_info)
    registry.register_private(agent_name="policy_query_agent", name="query_policy_status", tool=query_policy_status)
    registry.register_private(agent_name="policy_query_agent", name="update_policy_status", tool=update_policy_status, is_write=True)
    registry.register_private(agent_name="claim_agent", name="query_claim_case", tool=query_claim_case)
    registry.register_private(agent_name="claim_agent", name="query_claim_progress", tool=query_claim_progress)
