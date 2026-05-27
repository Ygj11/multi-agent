from __future__ import annotations

"""Internal Shuzhi LLM provider.

The provider owns only model transport and response normalization. It never
executes tools and never decides whether a tool is authorized.
"""

import json
import re
from time import perf_counter
from typing import Any, Optional

import httpx

from app.config.settings import Settings, get_settings
from app.llm.model_config import get_llm_model
from app.llm.schemas import LLMResponse
from app.observability.logger import log_event, preview_text


class InternalLLMProvider:
    """Calls the internal LLM HTTP endpoint and returns normalized responses."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.internal_llm_api_url

    def get_llm_model(self, scene: str | None = None, explicit_model: str | None = None) -> str:
        return get_llm_model(self.settings, scene=scene, explicit_model=explicit_model)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        scene: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> LLMResponse:
        started = perf_counter()
        actual_model = self.get_llm_model(scene=scene, explicit_model=model)
        if not self.base_url:
            response = self._local_fallback_response(
                messages=messages,
                tools=tools,
                model=actual_model,
                request_id=request_id,
                started=started,
            )
            self._log(scene, response)
            return response

        payload = self._build_payload(
            messages=messages,
            tools=tools,
            model=actual_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            async with httpx.AsyncClient(timeout=self.settings.internal_llm_timeout) as client:
                resp = await client.post(
                    self.base_url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )
            latency_ms = int((perf_counter() - started) * 1000)
            if resp.status_code != 200:
                response = LLMResponse(
                    content=None,
                    finish_reason="error",
                    error=f"internal_llm_http_{resp.status_code}: {resp.text}",
                    model=actual_model,
                    request_id=request_id,
                    latency_ms=latency_ms,
                    raw_response={"status_code": resp.status_code, "text": resp.text},
                )
                self._log(scene, response)
                return response
            response = self._parse_response(resp.json(), model=actual_model, request_id=request_id, latency_ms=latency_ms)
            self._log(scene, response)
            return response
        except Exception as exc:
            response = LLMResponse(
                content=None,
                finish_reason="error",
                error=str(exc),
                model=actual_model,
                request_id=request_id,
                latency_ms=int((perf_counter() - started) * 1000),
            )
            self._log(scene, response)
            return response

    def _build_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": self.settings.internal_llm_temperature if temperature is None else temperature,
            "max_tokens": self.settings.internal_llm_max_tokens if max_tokens is None else max_tokens,
        }
        if tools:
            payload["tools"] = tools
        return payload

    @staticmethod
    def _parse_response(
        data: dict[str, Any],
        *,
        model: str,
        request_id: str | None,
        latency_ms: int,
    ) -> LLMResponse:
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            return LLMResponse(
                content=None,
                finish_reason="error",
                error=f"incomplete_llm_response: {exc}",
                raw_response=data if isinstance(data, dict) else {"raw": data},
                model=model,
                request_id=request_id,
                latency_ms=latency_ms,
            )
        tool_calls = message.get("tool_calls") or []
        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            has_tool_calls=bool(tool_calls),
            reasoning_content=message.get("reasoning_content"),
            finish_reason=choice.get("finish_reason") or "stop",
            raw_response=data,
            model=model,
            request_id=request_id,
            latency_ms=latency_ms,
        )

    # 如果 internal_llm_api_url 没配置，就不请求真实模型，而是用本地写死逻辑模拟模型返回。todo 需要废弃
    def _local_fallback_response(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]],
        model: str,
        request_id: str | None,
        started: float,
    ) -> LLMResponse:
        """Deterministic offline behavior for local MVP tests when no URL is configured."""
        tool_names = [self._tool_name(tool) for tool in (tools or [])]
        called_tools = [message.get("name") for message in messages if message.get("role") == "tool"]
        text = "\n".join(str(message.get("content", "")) for message in messages)
        request_id_arg = self._find_request_id(text)
        policy_no = self._find_policy_no(text)
        claim_no = self._find_claim_no(text)
        next_calls: list[dict[str, Any]] = []

        if tool_names and not called_tools:
            if "query_internal_log" in tool_names:
                args = {"request_id": request_id_arg} if request_id_arg else {"query": text}
                next_calls.append(self._tool_call("call_query_internal_log", "query_internal_log", args))
                if "get_knowledge" in tool_names:
                    next_calls.append(self._tool_call("call_get_knowledge", "get_knowledge", {"query": text, "top_k": 3}))
                if "mcp.workflow.query_refund_task" in tool_names:
                    next_calls.append(
                        self._tool_call(
                            "call_mcp_workflow_refund",
                            "mcp.workflow.query_refund_task",
                            {"request_id": request_id_arg, "policy_no": policy_no},
                        )
                    )
            elif "query_policy_info" in tool_names:
                next_calls.append(self._tool_call("call_policy_info", "query_policy_info", {"policy_no": policy_no}))
                next_calls.append(self._tool_call("call_policy_status", "query_policy_status", {"policy_no": policy_no}))
            elif "query_claim_case" in tool_names:
                next_calls.append(self._tool_call("call_claim_case", "query_claim_case", {"claim_no": claim_no}))
                next_calls.append(self._tool_call("call_claim_progress", "query_claim_progress", {"claim_no": claim_no}))

        if next_calls:
            return LLMResponse(
                content=None,
                tool_calls=next_calls,
                has_tool_calls=True,
                finish_reason="tool_calls",
                model=model,
                request_id=request_id,
                latency_ms=int((perf_counter() - started) * 1000),
            )

        return LLMResponse(
            content=self._final_content(text, called_tools),
            tool_calls=[],
            has_tool_calls=False,
            finish_reason="stop",
            model=model,
            request_id=request_id,
            latency_ms=int((perf_counter() - started) * 1000),
        )

    @staticmethod
    def _tool_name(tool: dict[str, Any]) -> str | None:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict):
            return function.get("name")
        return tool.get("name") if isinstance(tool, dict) else None

    @staticmethod
    def _tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
        }

    @staticmethod
    def _find_request_id(text: str) -> str | None:
        match = re.search(r"\bREQ[_-]?[A-Za-z0-9]+\b", text)
        return match.group(0) if match else None

    @staticmethod
    def _find_policy_no(text: str) -> str | None:
        match = re.search(r"(?:policy_no|保单|淇濆崟)\D*([A-Za-z0-9]{6,})", text, re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _find_claim_no(text: str) -> str | None:
        match = re.search(r"\b(?:CLM|CLAIM)[_-]?[A-Za-z0-9]{3,}\b", text, re.IGNORECASE)
        return match.group(0) if match else None

    @staticmethod
    def _final_content(text: str, called_tools: list[Any]) -> str:
        if "query_internal_log" in called_tools or "mcp.workflow.query_refund_task" in called_tools:
            return (
                "E102 通常表示签名校验失败。结合内部日志、知识库和 MCP workflow 工具观察，"
                "重点检查 timestamp 是否参与签名、密钥版本、字段排序、空值处理和 body 序列化方式。"
                "如 MCP workflow 工具显示退保任务卡在签名或回调节点，需要继续核对上下游任务状态。"
            )
        if "query_policy_info" in called_tools:
            return "保单查询完成：已查询保单基础信息和状态，请以工具返回的脱敏结果为准。"
        if "query_claim_case" in called_tools:
            return "理赔查询完成：已查询赔案信息和处理进度，请以工具返回的脱敏结果为准。"
        if "compliance" in text.lower() or "合规" in text or "鍚堣" in text:
            risk = "high" if any(marker in text for marker in ("13800138000", "110101199003074233", "token", "secret")) else "low"
            return f"合规安全检查 completed: 风险等级 {risk}. Sensitive fields must be redacted before external sharing."
        return "已完成任务分析。"

    @staticmethod
    def _log(scene: str | None, response: LLMResponse) -> None:
        log_event(
            "llm_chat_finished",
            request_id=response.request_id,
            node="llm_provider",
            message="LLM chat finished",
            data={
                "scene": scene,
                "model": response.model,
                "latency_ms": response.latency_ms,
                "finish_reason": response.finish_reason,
                "error": response.error,
                "content_preview": preview_text(response.content or ""),
                "tool_call_count": len(response.tool_calls),
            },
        )
