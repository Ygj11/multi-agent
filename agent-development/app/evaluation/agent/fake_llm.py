from __future__ import annotations

"""Agent Eval 专用 Fake LLM。

Fake LLM 只模拟模型输出，不执行工具，也不修改运行时状态。它记录每次调用，
让 Eval 可以断言真实主图是否按预期请求了 query rewrite、tool loop、
completion verifier 和 final compliance。
"""

import json
from typing import Any

from app.evaluation.agent.schemas import (
    AgentEvalLLMCallTrace,
    AgentEvalLLMResponseSpec,
    AgentEvalLLMScriptedResponse,
    AgentEvalToolCallSpec,
)
from app.llm.schemas import LLMResponse


class AgentEvalFakeLLM:
    """按 scene 顺序消费脚本响应的 LLMProvider 兼容对象。"""

    def __init__(self, script: list[AgentEvalLLMScriptedResponse]) -> None:
        self.script = script
        self.calls: list[AgentEvalLLMCallTrace] = []
        self._used_indexes: set[int] = set()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        scene = kwargs.get("scene")
        index, item = self._match(scene=scene, messages=messages)
        if item is None:
            response = self._default_response(scene)
            self.calls.append(
                AgentEvalLLMCallTrace(
                    scene=scene,
                    request_id=kwargs.get("request_id"),
                    trace_id=kwargs.get("trace_id"),
                    session_key=kwargs.get("session_key"),
                    tool_names=self._tool_names(tools or []),
                    matched_index=None,
                    exhausted=response.finish_reason == "error",
                )
            )
            return response

        if not item.repeat:
            self._used_indexes.add(index)
        self.calls.append(
            AgentEvalLLMCallTrace(
                scene=scene,
                request_id=kwargs.get("request_id"),
                trace_id=kwargs.get("trace_id"),
                session_key=kwargs.get("session_key"),
                tool_names=self._tool_names(tools or []),
                matched_index=index,
                exhausted=False,
            )
        )
        return self._response(item.response, index=index)

    def _match(
        self,
        *,
        scene: str | None,
        messages: list[dict[str, Any]],
    ) -> tuple[int, AgentEvalLLMScriptedResponse | None]:
        text = "\n".join(str(message.get("content") or "") for message in messages)
        for index, item in enumerate(self.script):
            if index in self._used_indexes:
                continue
            if item.scene != scene:
                continue
            if item.match_contains and not all(token in text for token in item.match_contains):
                continue
            return index, item
        return -1, None

    @staticmethod
    def _response(spec: AgentEvalLLMResponseSpec, *, index: int) -> LLMResponse:
        if spec.error:
            return LLMResponse(
                content=spec.content,
                finish_reason="error",
                error=spec.error,
                model=spec.model,
            )
        content = spec.content
        if spec.content_json is not None:
            content = json.dumps(spec.content_json, ensure_ascii=False)
        tool_calls = [AgentEvalFakeLLM._tool_call(call, index=index, offset=offset) for offset, call in enumerate(spec.tool_calls)]
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            has_tool_calls=bool(tool_calls),
            finish_reason=spec.finish_reason or ("tool_calls" if tool_calls else "stop"),
            model=spec.model,
        )

    @staticmethod
    def _tool_call(call: AgentEvalToolCallSpec, *, index: int, offset: int) -> dict[str, Any]:
        call_id = call.id or f"agent_eval_call_{index}_{offset}_{call.name}"
        return {
            "id": call_id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments, ensure_ascii=False, default=str),
            },
        }

    @staticmethod
    def _tool_names(tools: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if isinstance(function, dict) and function.get("name"):
                names.append(str(function["name"]))
        return names

    @staticmethod
    def _default_response(scene: str | None) -> LLMResponse:
        # summary / final_compliance 在主链路末端经常被动调用；缺少脚本时给安全默认值，
        # 避免每个行为 Eval case 都重复声明这些非核心响应。
        if scene in {"summary", "memory_summary"}:
            return LLMResponse(content="Agent Eval summary.", finish_reason="stop", model="agent-eval-fake")
        if scene == "final_compliance":
            return LLMResponse(content="ok", finish_reason="stop", model="agent-eval-fake")
        return LLMResponse(
            content=None,
            finish_reason="error",
            error=f"llm_script_exhausted:{scene}",
            model="agent-eval-fake",
        )
