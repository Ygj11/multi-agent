from __future__ import annotations

"""POS query tool handlers backed by PosAPIClient."""

from typing import Any, Callable

from app.auth.principal import principal_from_auth_context
from app.integrations.pos_api_client import PosAPIClient


POS_AVAILABLE_ITEMS_PATH = "/process/api/i/endotItemType/list"
POS_SURRENDER_PREMIUM_PATH = "/process/api/premium/calc"
POS_POLICY_STANDARD_PATH = "/epos/policy/standard/query"
POS_APPROVAL_TEXT_PATH = "/epos/task/report/queryPreserveChangeDetail"
POS_SUBMIT_VERIFY_PATH = "/process/process/submitVerify"


def build_pos_query_available_items_tool(pos_api_client: PosAPIClient) -> Callable[..., Any]:
    async def tool(
        policyNo: str | None = None,
        customerNo: str | None = None,
        src: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = {
            "policyNo": policyNo,
            "src": src if src is not None else 16,
            "currentLoginUserInfo": {"customerNo": customerNo},
        }
        return await pos_api_client.post(POS_AVAILABLE_ITEMS_PATH, payload)

    return tool


def build_pos_calc_surrender_premium_tool(pos_api_client: PosAPIClient) -> Callable[..., Any]:
    async def tool(
        applyDate: int | None = None,
        policyNo: str | None = None,
        endorseType: str | None = None,
        taskSrc: str | None = None,
        surrenderType: str | None = None,
        surDate: int | None = None,
        commission: str | None = None,
        operatorId: str | None = None,
        auth_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = {
            "applyDate": applyDate,
            "policyNo": policyNo,
            "endorseType": endorseType or "001028",
            "taskSrc": taskSrc or "01",
            "surrenderType": surrenderType or "1",
            "surDate": surDate,
            "commission": commission or "1",
            "operatorId": _operator_id(auth_context, operatorId),
        }
        return await pos_api_client.post(POS_SURRENDER_PREMIUM_PATH, payload)

    return tool


def build_pos_query_policy_standard_tool(pos_api_client: PosAPIClient) -> Callable[..., Any]:
    async def tool(
        policyNo: str | None = None,
        withInsureds: str | None = None,
        extensions: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = {
            "polNo": policyNo,
            "withInsureds": withInsureds or "Y",
            "extensions": extensions or ["pollist", "assuredPolicyInfo", "pollLock"],
        }
        return await pos_api_client.post(POS_POLICY_STANDARD_PATH, payload)

    return tool


def build_pos_query_approval_text_tool(pos_api_client: PosAPIClient) -> Callable[..., Any]:
    async def tool(
        applySeq: str | None = None,
        pageSize: int | None = None,
        pageNo: int | None = None,
        operatorId: str | None = None,
        auth_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = {
            "applySeq": applySeq,
            "pageSize": 0 if pageSize is None else pageSize,
            "pageNo": 1 if pageNo is None else pageNo,
            "operatorId": _operator_id(auth_context, operatorId),
        }
        return await pos_api_client.post(POS_APPROVAL_TEXT_PATH, payload)

    return tool


def build_pos_submit_verify_tool(pos_api_client: PosAPIClient) -> Callable[..., Any]:
    async def tool(
        policyNo: str | None = None,
        endorseType: str | None = None,
        payMode: str | None = None,
        acceptDate: int | None = None,
        surrenderReason: str | None = None,
        taskSrc: str | None = None,
        operatorId: str | None = None,
        auth_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = {
            "data": {
                "acceptInfo": {
                    "acceptDate": acceptDate,
                    "endorseType": endorseType or "001028",
                    "surrenderReason": surrenderReason or "11",
                    "taskSrc": taskSrc or "31",
                },
                "chargeRefundInfo": {
                    "accountInfos": [{"payMode": payMode or "Y"}],
                    "policyInfos": {"policyNo": policyNo},
                },
                "operatorId": _operator_id(auth_context, operatorId),
            }
        }
        return await pos_api_client.post(POS_SUBMIT_VERIFY_PATH, payload)

    return tool


def _operator_id(auth_context: dict[str, Any] | None, fallback: str | None) -> str | None:
    principal = principal_from_auth_context(auth_context)
    if principal is not None:
        return principal.effective_user_id
    return fallback
