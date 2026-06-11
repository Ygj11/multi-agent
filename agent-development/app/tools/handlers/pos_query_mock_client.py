from __future__ import annotations

"""Mock POS client used by POS_TOOL_MODE=mock."""

from typing import Any


class MockPosAPIClient:
    """Small in-process POS stand-in with the same `.post()` boundary as PosAPIClient."""

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "mock": True,
            "path": path,
            "url": f"mock://pos{path}",
            "request_payload": payload,
            "response": self._response(path, payload),
            "status_code": 200,
            "error": None,
            "duration_ms": 0,
        }

    @staticmethod
    def _response(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if path.endswith("/endotItemType/list"):
            return {
                "available_items": [
                    {"endorseType": "001028", "name": "退保"},
                    {"endorseType": "001029", "name": "联系方式变更"},
                ],
                "policyNo": payload.get("policyNo"),
            }
        if path.endswith("/premium/calc"):
            return {
                "policyNo": payload.get("policyNo"),
                "endorseType": payload.get("endorseType"),
                "surrender_premium": 1288.88,
                "currency": "CNY",
            }
        if path.endswith("/policy/standard/query"):
            return {
                "polNo": payload.get("polNo"),
                "policy_status": "有效",
                "pollLock": "N",
            }
        if path.endswith("/task/report/queryPreserveChangeDetail"):
            return {
                "applySeq": payload.get("applySeq"),
                "approval_text": "mock 保全批文内容",
                "change_items": ["保全任务完成", "保单信息已更新"],
            }
        if path.endswith("/process/submitVerify"):
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            policy_infos = data.get("chargeRefundInfo", {}).get("policyInfos", {})
            return {
                "policyNo": policy_infos.get("policyNo"),
                "verify_result": "PASS",
                "message": "mock submit verify passed",
            }
        return {"message": "mock POS response"}
