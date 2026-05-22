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
    stopped_reason: Literal["final", "error", "max_iterations"]
    iterations: int
    messages: list[dict[str, Any]]
    error: str | None = None


class ToolCallingRunner:
    """Owns the complete LLM -> tool -> observation loop."""

    def __init__(
        self,
        *,
        llm_provider: LLMProvider,
        tool_executor: ToolExecutor,
        max_iterations: int = 30,
    ) -> None:
        self.llm_provider = llm_provider
        self.tool_executor = tool_executor
        self.max_iterations = max_iterations

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

        for iteration in range(1, limit + 1):
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
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": normalized.id,
                                "name": normalized.name or "unknown",
                                "content": json.dumps(observation, ensure_ascii=False, default=str),
                            }
                        )
                        continue

                    tool_result = await self.tool_executor.execute(
                        agent_name=agent_name,
                        tool_name=normalized.name,
                        arguments=normalized.arguments,
                        agent_card=agent_card,
                        session_key=session_key,
                        request_id=request_id,
                        trace_id=trace_id,
                    )
                    dumped = tool_result.model_dump()
                    executed_calls.append(dumped)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": normalized.id,
                            "name": normalized.name,
                            "content": json.dumps(dumped, ensure_ascii=False, default=str),
                        }
                    )
                continue

            messages.append({"role": "assistant", "content": response.content or ""})
            return ToolCallingRunResult(
                final_answer=response.content or "",
                tool_calls=executed_calls,
                stopped_reason="final",
                iterations=iteration,
                messages=messages,
            )

        error = f"tool_calling_runner_exceeded_max_iterations:{limit}"
        return ToolCallingRunResult(
            final_answer="",
            tool_calls=executed_calls,
            stopped_reason="max_iterations",
            iterations=limit,
            messages=messages,
            error=error,
        )

    @staticmethod
    def _tool_name(tool: dict[str, Any]) -> str | None:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict):
            return function.get("name")
        return tool.get("name") if isinstance(tool, dict) else None

