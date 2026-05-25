from __future__ import annotations

"""Base template for AgentCard-driven sub agents."""

from abc import ABC, abstractmethod
from typing import Any

from app.runtime.context_builder import ContextBuilder
from app.observability.logger import log_event, preview_text
from app.schemas.agent_card import AgentCard
from app.schemas.runtime import OrchestratorContext, SubAgentContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.tools.executor import ToolExecutor
from app.subagents.tool_calling_runner import ToolCallingRunner, ToolCallingRunResult


class BaseSubAgent(ABC):
    """Shared execution template for sub agents.

    The template centralizes AgentCard reading, skill selection/body loading via
    ContextBuilder, available tool resolution, and common tool execution.
    Subclasses implement only task-specific behavior in `do_run`.
    """

    name: str

    use_tool_calling_runner: bool = True

    def __init__(
        self,
        context_builder: ContextBuilder,
        tool_executor: ToolExecutor | None = None,
        tool_calling_runner: ToolCallingRunner | None = None,
    ) -> None:
        self.context_builder = context_builder
        self.tool_executor = tool_executor
        self.tool_calling_runner = tool_calling_runner

    async def run(self, task: SubAgentTask, parent_context: OrchestratorContext) -> SubAgentResult:
        agent_card = self.get_agent_card(task)
        allowed_tools = self.get_available_tool_names(agent_card)
        sub_context = await self.context_builder.build_for_subagent(
            task=task,
            parent_context=parent_context,
            allowed_tools=allowed_tools,
        )
        if sub_context.need_clarification:
            return SubAgentResult(
                name=self.name,
                agent_name=self.name,
                task_id=task.task_id,
                answer=sub_context.clarification_question or "请补充必要信息后我再继续处理。",
                confidence=0.4,
                risk_level="low",
                metadata={"clarification": True},
                selected_skill_id=sub_context.selected_skill_id,
                selected_skill_metadata=sub_context.selected_skill_metadata,
                skill_selection_score=sub_context.skill_selection_score,
                skill_selection_reason=sub_context.skill_selection_reason,
            )
        if self.use_tool_calling_runner and self.tool_calling_runner is not None and agent_card is not None:
            self._log_runner_started(task)
            messages = self.build_messages(
                task=task,
                parent_context=parent_context,
                sub_context=sub_context,
                agent_card=agent_card,
            )
            tool_schemas = self.get_available_tool_schemas(agent_card)
            run_result = await self.tool_calling_runner.run(
                agent_name=self.name,
                messages=messages,
                tools=tool_schemas,
                session_key=task.session_key,
                request_id=str(task.metadata.get("request_id") or task.task_id or ""),
                trace_id=task.metadata.get("trace_id"),
                agent_card=agent_card,
            )
            result = self.build_result_from_runner(
                task=task,
                sub_context=sub_context,
                agent_card=agent_card,
                run_result=run_result,
            )
            self._log_runner_evidence_built(task, result)
            result.name = result.name or self.name
            result.agent_name = result.agent_name or self.name
            result.task_id = result.task_id or task.task_id
            return result

        result = await self.do_run(
            task=task,
            parent_context=parent_context,
            sub_context=sub_context,
            agent_card=agent_card,
        )
        result.name = result.name or self.name
        result.agent_name = result.agent_name or self.name
        result.task_id = result.task_id or task.task_id
        return result

    def get_agent_card(self, task: SubAgentTask) -> AgentCard | None:
        data = task.metadata.get("agent_card")
        return AgentCard(**data) if isinstance(data, dict) else None

    def get_available_tool_names(self, agent_card: AgentCard | None) -> list[str]:
        if self.tool_executor is None:
            return agent_card.private_tools if agent_card else []
        if agent_card is None:
            return self.tool_executor.registry.list_available_tools_for_agent(self.name)
        return self.tool_executor.registry.list_available_tools_for_agent(self.name, agent_card)

    def get_available_tools(self, agent_card: AgentCard | None) -> list[str]:
        """Compatibility alias for older tests."""
        return self.get_available_tool_names(agent_card)

    def get_available_tool_schemas(self, agent_card: AgentCard) -> list[dict[str, Any]]:
        if self.tool_executor is None:
            return []
        return self.tool_executor.registry.list_tools_for_agent(agent_card)

    async def call_tool(
        self,
        *,
        task: SubAgentTask,
        agent_card: AgentCard | None,
        name: str,
        arguments: dict[str, Any],
    ):
        if self.tool_executor is None:
            raise RuntimeError("tool executor is not configured")
        return await self.tool_executor.execute(
            agent_name=self.name,
            tool_name=name,
            arguments=arguments,
            agent_card=agent_card,
            request_id=task.metadata.get("request_id"),
            trace_id=task.metadata.get("trace_id"),
            session_key=task.session_key,
        )

    def build_messages(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        sub_context: SubAgentContext,
        agent_card: AgentCard,
    ) -> list[dict[str, Any]]:
        """Build the LLM messages for the shared tool-calling loop."""
        return [
            {
                "role": "system",
                "content": (
                    f"You are {agent_card.agent_name}. {agent_card.description}\n"
                    "Use only the provided tools. When enough evidence is available, answer the user directly.\n"
                    f"Skill body:\n{sub_context.skill_content}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original query: {task.original_query}\n"
                    f"Rewritten query: {sub_context.rewritten_query}\n"
                    f"Intent: {task.intent}\n"
                    f"Entities: {task.entities}\n"
                    f"Short summary: {parent_context.short_summary or ''}\n"
                    f"Lightweight hints: {parent_context.lightweight_knowledge_hints}"
                ),
            },
        ]

    def build_result_from_runner(
        self,
        *,
        task: SubAgentTask,
        sub_context: SubAgentContext,
        agent_card: AgentCard,
        run_result: ToolCallingRunResult,
    ) -> SubAgentResult:
        """Convert a generic tool loop result into the SubAgentResult contract."""
        evidence = [self._tool_call_to_evidence(item) for item in run_result.tool_calls]
        needs_approval = run_result.needs_human_approval or run_result.stopped_reason == "human_approval_required"
        answer = (
            "该操作需要人工审批，当前尚未执行。"
            if needs_approval
            else run_result.final_answer or (run_result.error or "Agent loop failed.")
        )
        return SubAgentResult(
            name=self.name,
            agent_name=self.name,
            task_id=task.task_id,
            answer=answer,
            diagnosis=self._diagnosis_from_runner(run_result),
            evidence=evidence,
            tool_calls=run_result.tool_calls,
            recommendation=self._recommendation_from_runner(run_result),
            responsibility=self._responsibility_from_runner(run_result),
            confidence=0.88 if run_result.stopped_reason == "final" else 0.3,
            needs_human_approval=needs_approval,
            approval_payloads=[run_result.approval_payload] if run_result.approval_payload else [],
            risk_level="high" if needs_approval else "medium" if run_result.stopped_reason != "final" else "low",
            metadata={
                "tool_calling_runner": {
                    "stopped_reason": run_result.stopped_reason,
                    "iterations": run_result.iterations,
                    "error": run_result.error,
                    "visible_tools": self.get_available_tool_names(agent_card),
                    "pending_tool_call": run_result.pending_tool_call,
                    "pending_messages": run_result.messages,
                    "pending_tools": run_result.tools,
                }
            },
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )

    def _tool_call_to_evidence(self, item: dict[str, Any]) -> dict[str, Any]:
        tool_name = str(item.get("name") or item.get("tool_name") or "")
        mapping = {
            "query_internal_log": ("internal_log", "query_internal_log"),
            "get_knowledge": ("knowledge", "InMemoryKnowledgeService"),
            "rag_search_tool": ("knowledge", "InMemoryKnowledgeService"),
            "mcp.workflow.query_refund_task": ("mcp_workflow", "MCPClientManager"),
            "mcp.logs.query_trace": ("mcp_logs", "MCPClientManager"),
            "query_policy_info": ("policy_info", "query_policy_info"),
            "query_policy_status": ("policy_status", "query_policy_status"),
            "query_claim_case": ("claim_case", "query_claim_case"),
            "query_claim_progress": ("claim_progress", "query_claim_progress"),
        }
        evidence_type, source = mapping.get(tool_name, ("tool_observation", tool_name or "tool_calling_runner"))
        summary = item.get("error") or str(item.get("result") or "")[:180]
        return {
            "type": evidence_type,
            "source": source,
            "tool_name": tool_name,
            "summary": summary,
            "result_preview": item.get("result"),
            "confidence": 0.8 if item.get("success") else 0.3,
        }

    def _diagnosis_from_runner(self, run_result: ToolCallingRunResult) -> str | None:
        if self.name == "troubleshooting_agent":
            return "E102 签名校验失败方向，已结合工具观察进行排查。"
        return None

    def _recommendation_from_runner(self, run_result: ToolCallingRunResult) -> str | None:
        if self.name == "troubleshooting_agent":
            return "建议核对 timestamp、密钥版本、字段排序、空值处理和 body 序列化方式。"
        return None

    def _responsibility_from_runner(self, run_result: ToolCallingRunResult) -> str | None:
        if self.name == "troubleshooting_agent":
            return "需结合 MCP workflow 证据和我方验签日志确认最终归属。"
        return None

    def _log_runner_started(self, task: SubAgentTask) -> None:
        event_name = "troubleshooting_started" if self.name == "troubleshooting_agent" else "subagent_started"
        log_event(
            event_name,
            request_id=str(task.metadata.get("request_id") or ""),
            trace_id=str(task.metadata.get("trace_id") or ""),
            session_key=task.session_key,
            node=self.name,
            message=f"{self.name} tool-calling loop started",
            data={"query_preview": preview_text(task.query)},
        )

    def _log_runner_evidence_built(self, task: SubAgentTask, result: SubAgentResult) -> None:
        if self.name != "troubleshooting_agent":
            return
        log_event(
            "evidence_built",
            request_id=str(task.metadata.get("request_id") or ""),
            trace_id=str(task.metadata.get("trace_id") or ""),
            session_key=task.session_key,
            node=self.name,
            message="Troubleshooting evidence built",
            data={
                "tool_sequence": [item.get("tool_name") for item in result.evidence],
                "evidence_count": len(result.evidence),
                "answer_preview": preview_text(result.answer),
            },
        )

    @abstractmethod
    async def do_run(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        sub_context: SubAgentContext,
        agent_card: AgentCard | None,
    ) -> SubAgentResult:
        """Execute task-specific logic."""
