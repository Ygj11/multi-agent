from __future__ import annotations

"""Troubleshooting tool handlers backed by real APIs."""

from typing import Any, Callable

from app.integrations.troubleshooting_api_client import TroubleshootingAPIClient


def build_query_task_status_tool(client: TroubleshootingAPIClient) -> Callable[..., Any]:
    async def tool(request_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return await client.query_task_status(request_id)

    return tool


def build_query_node_status_tool(client: TroubleshootingAPIClient) -> Callable[..., Any]:
    async def tool(request_id: str | None = None, node_name: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return await client.query_node_status(request_id, node_name)

    return tool


def build_query_internal_log_tool(client: TroubleshootingAPIClient) -> Callable[..., Any]:
    async def tool(request_id: str | None = None, query: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return await client.query_internal_log(request_id=request_id, query=query)

    return tool


def build_query_endo_task_record_tool(client: TroubleshootingAPIClient) -> Callable[..., Any]:
    async def tool(apply_seq: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return await client.query_endo_task_record(apply_seq)

    return tool


def build_notice_policy_update_tool(client: TroubleshootingAPIClient) -> Callable[..., Any]:
    async def tool(
        apply_seq: str | None = None,
        policyNo: str | None = None,
        endorseType: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await client.notice_policy_update(apply_seq=apply_seq, policyNo=policyNo, endorseType=endorseType)

    return tool


def build_notice_customer_update_tool(client: TroubleshootingAPIClient) -> Callable[..., Any]:
    async def tool(
        apply_seq: str | None = None,
        policyNo: str | None = None,
        endorseType: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await client.notice_customer_update(apply_seq=apply_seq, policyNo=policyNo, endorseType=endorseType)

    return tool


def build_notice_period_update_tool(client: TroubleshootingAPIClient) -> Callable[..., Any]:
    async def tool(
        apply_seq: str | None = None,
        policyNo: str | None = None,
        endorseType: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await client.notice_period_update(apply_seq=apply_seq, policyNo=policyNo, endorseType=endorseType)

    return tool


def build_policy_suspend_or_recovery_tool(client: TroubleshootingAPIClient) -> Callable[..., Any]:
    async def tool(
        handleType: str | None = None,
        premHandleFlag: str | None = None,
        reqList: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await client.policy_suspend_or_recovery(
            handleType=handleType,
            premHandleFlag=premHandleFlag,
            reqList=reqList,
        )

    return tool


def build_notice_finance_tool(client: TroubleshootingAPIClient) -> Callable[..., Any]:
    async def tool(
        apply_seq: str | None = None,
        policyNo: str | None = None,
        endorseType: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await client.notice_finance(apply_seq=apply_seq, policyNo=policyNo, endorseType=endorseType)

    return tool
