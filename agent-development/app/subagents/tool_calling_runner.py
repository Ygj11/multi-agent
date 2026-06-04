from __future__ import annotations

"""Reusable Agent loop for LLM tool calling."""

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.llm.base import LLMProvider
from app.llm.tool_call_parser import normalize_tool_call
from app.observability.logger import log_event
from app.schemas.agent_card import AgentCard
from app.tools.executor import ToolExecutor


class ToolCallingRunResult(BaseModel):
    """Result of a tool-calling Agent loop."""

    final_answer: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    stopped_reason: Literal[
        "final",
        "error",
        "max_iterations",
        "human_approval_required",
        "max_consecutive_tool_failures",
        "max_same_tool_failures",
        "max_duplicate_tool_calls",
    ]
    iterations: int
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    needs_human_approval: bool = False
    approval_payload: dict[str, Any] | None = None
    pending_tool_call: dict[str, Any] | None = None


class ToolCallingRunner:
    """Owns the complete LLM -> tool -> observation loop."""

    def __init__(
        self,
        *,
        llm_provider: LLMProvider,
        tool_executor: ToolExecutor,
        max_iterations: int = 10,
        max_consecutive_tool_failures: int = 3,
        max_same_tool_failures: int = 2,
        max_duplicate_tool_calls: int = 2,
    ) -> None:
        self.llm_provider = llm_provider
        self.tool_executor = tool_executor
        self.max_iterations = max_iterations
        self.max_consecutive_tool_failures = max_consecutive_tool_failures
        self.max_same_tool_failures = max_same_tool_failures
        self.max_duplicate_tool_calls = max_duplicate_tool_calls

    async def run(
        self,
        *,
        agent_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        session_key: str,
        request_id: str,
        trace_id: str | None = None,
        max_iterations: int | None = None,
        agent_card: AgentCard | None = None,
        principal: dict[str, Any] | None = None,
        auth_context: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> ToolCallingRunResult:
        limit = max_iterations or self.max_iterations
        visible_tool_names = [self._tool_name(tool) for tool in tools]
        log_event(
            "tool_calling_runner_started",
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            node="tool_calling_runner",
            message="Tool calling loop started",
            data={"agent_name": agent_name, "available_tools": visible_tool_names, "max_iterations": limit},
        )
        executed_calls: list[dict[str, Any]] = []
        consecutive_failures = 0
        same_tool_failure_counts: dict[str, int] = {}
        tool_call_counts: dict[str, int] = {}

        for iteration in range(1, limit + 1):
            """Call the LLM with the current messages and tools, and get the response, which may include tool calls."""
            response = await self.llm_provider.chat(
                messages=messages,
                tools=tools,
                scene="subagent_reasoning",
                request_id=request_id,
            )
            
            if response.finish_reason == "error":
                return ToolCallingRunResult(
                    final_answer="",
                    tool_calls=executed_calls,
                    stopped_reason="error",
                    iterations=iteration,
                    messages=messages,
                    tools=tools,
                    error=response.error or "llm_error",
                )

            if response.has_tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": response.tool_calls,
                    }
                )
                for raw_call in response.tool_calls:
                    normalized = normalize_tool_call(raw_call)
                    if normalized.error:
                        observation = {
                            "success": False,
                            "error": normalized.error,
                            "raw_tool_call": normalized.raw,
                        }
                        executed_calls.append(observation)
                        consecutive_failures += 1
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": normalized.id,
                                "name": normalized.name or "unknown",
                                "content": json.dumps(observation, ensure_ascii=False, default=str),
                            }
                        )
                        if consecutive_failures >= self.max_consecutive_tool_failures:
                            return self._stop_for_guardrail(
                                reason="max_consecutive_tool_failures",
                                executed_calls=executed_calls,
                                iteration=iteration,
                                messages=messages,
                                tools=tools,
                            )
                        continue

                    tool_call_key = self._tool_call_key(normalized.name, normalized.arguments)
                    tool_call_counts[tool_call_key] = tool_call_counts.get(tool_call_key, 0) + 1
                    if tool_call_counts[tool_call_key] > self.max_duplicate_tool_calls:
                        observation = {
                            "name": normalized.name,
                            "agent_name": agent_name,
                            "allowed": False,
                            "success": False,
                            "error": "max_duplicate_tool_calls",
                            "arguments": normalized.arguments,
                            "tool_call_id": normalized.id,
                        }
                        executed_calls.append(observation)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": normalized.id,
                                "name": normalized.name,
                                "content": json.dumps(observation, ensure_ascii=False, default=str),
                            }
                        )
                        return self._stop_for_guardrail(
                            reason="max_duplicate_tool_calls",
                            executed_calls=executed_calls,
                            iteration=iteration,
                            messages=messages,
                            tools=tools,
                        )

                    """Execute the tool call and capture the result, including success status, errors, 
                    and any relevant metadata."""
                    tool_result = await self.tool_executor.execute(
                        agent_name=agent_name,
                        tool_name=normalized.name,
                        arguments=normalized.arguments,
                        agent_card=agent_card,
                        session_key=session_key,
                        request_id=request_id,
                        trace_id=trace_id,
                        principal=principal,
                        auth_context=auth_context,
                        evidence=evidence or executed_calls,
                    )
                    dumped = tool_result.model_dump()
                    executed_calls.append(dumped)
                    if tool_result.success:
                        consecutive_failures = 0
                        same_tool_failure_counts[tool_call_key] = 0
                    else:
                        consecutive_failures += 1
                        same_tool_failure_counts[tool_call_key] = same_tool_failure_counts.get(tool_call_key, 0) + 1
                    if tool_result.needs_human_approval or tool_result.error == "human_approval_required":
                        pending_tool_call = dumped.get("pending_tool_call") or {
                            "name": normalized.name,
                            "arguments": normalized.arguments,
                            "tool_call_id": normalized.id,
                        }
                        pending_tool_call.setdefault("tool_call_id", normalized.id)
                        pending_tool_call.setdefault("name", normalized.name)
                        pending_tool_call.setdefault("arguments", normalized.arguments)
                        return ToolCallingRunResult(
                            final_answer="",
                            tool_calls=executed_calls,
                            stopped_reason="human_approval_required",
                            iterations=iteration,
                            messages=messages,
                            tools=tools,
                            error="human_approval_required",
                            needs_human_approval=True,
                            approval_payload=dumped.get("approval_payload"),
                            pending_tool_call=pending_tool_call,
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": normalized.id,
                            "name": normalized.name,
                            "content": json.dumps(dumped, ensure_ascii=False, default=str),
                        }
                    )
                    if consecutive_failures >= self.max_consecutive_tool_failures:
                        return self._stop_for_guardrail(
                            reason="max_consecutive_tool_failures",
                            executed_calls=executed_calls,
                            iteration=iteration,
                            messages=messages,
                            tools=tools,
                        )
                    if same_tool_failure_counts[tool_call_key] >= self.max_same_tool_failures:
                        return self._stop_for_guardrail(
                            reason="max_same_tool_failures",
                            executed_calls=executed_calls,
                            iteration=iteration,
                            messages=messages,
                            tools=tools,
                        )
                continue

            messages.append({"role": "assistant", "content": response.content or ""})
            return ToolCallingRunResult(
                final_answer=response.content or "",
                tool_calls=executed_calls,
                stopped_reason="final",
                iterations=iteration,
                messages=messages,
                tools=tools,
            )

        error = f"tool_calling_runner_exceeded_max_iterations:{limit}"
        return ToolCallingRunResult(
            final_answer="",
            tool_calls=executed_calls,
            stopped_reason="max_iterations",
            iterations=limit,
            messages=messages,
            tools=tools,
            error=error,
        )

    @staticmethod
    def _tool_name(tool: dict[str, Any]) -> str | None:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict):
            return function.get("name")
        return tool.get("name") if isinstance(tool, dict) else None

    @staticmethod
    def _tool_call_key(tool_name: str, arguments: dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)}"

    @staticmethod
    def _stop_for_guardrail(
        *,
        reason: Literal["max_consecutive_tool_failures", "max_same_tool_failures", "max_duplicate_tool_calls"],
        executed_calls: list[dict[str, Any]],
        iteration: int,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ToolCallingRunResult:
        return ToolCallingRunResult(
            final_answer="工具调用连续失败或重复调用，已停止自动处理，请人工介入。",
            tool_calls=executed_calls,
            stopped_reason=reason,
            iterations=iteration,
            messages=messages,
            tools=tools,
            error=reason,
        )
