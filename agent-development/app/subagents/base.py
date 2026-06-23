from __future__ import annotations

"""Base template for AgentCard-driven sub agents."""

from abc import ABC, abstractmethod
from typing import Any

from app.agents.card_loader import AgentCardLoader
from app.auth.principal import principal_dict_from_auth_context
from app.prompts.loader import PromptLoader, default_prompt_loader
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
        agent_card_loader: AgentCardLoader,
        tool_executor: ToolExecutor | None = None,
        tool_calling_runner: ToolCallingRunner | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.context_builder = context_builder
        self.agent_card_loader = agent_card_loader
        self.tool_executor = tool_executor
        self.tool_calling_runner = tool_calling_runner
        self.prompt_loader = prompt_loader or default_prompt_loader

    async def run(self, task: SubAgentTask, parent_context: OrchestratorContext) -> SubAgentResult:
        agent_card = self.get_agent_card(task)
        allowed_tools = self.get_available_tool_names(agent_card)
        sub_context = await self.context_builder.build_for_subagent(
            task=task,
            parent_context=parent_context,
            agent_card=agent_card,
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
                metadata={
                    "clarification": True,
                    "clarification_source": "skill_selection" if sub_context.no_skill_blocked else "skill_required_entities",
                    "clarification_question": sub_context.clarification_question,
                    "missing_required_entities": sub_context.missing_required_entities,
                    "entities": task.entities,
                    "no_skill_blocked": sub_context.no_skill_blocked,
                    "no_skill_policy": sub_context.no_skill_policy,
                    "skill_selection_source": sub_context.skill_selection_source,
                    "skill_selection_fallback": sub_context.skill_selection_fallback,
                    "skill_selection_decision_trace": task.metadata.get("skill_selection_decision_trace"),
                },
                selected_skill_id=sub_context.selected_skill_id,
                selected_skill_metadata=sub_context.selected_skill_metadata,
                skill_selection_score=sub_context.skill_selection_score,
                skill_selection_reason=sub_context.skill_selection_reason,
            )
        if sub_context.no_skill_blocked:
            return SubAgentResult(
                name=self.name,
                agent_name=self.name,
                task_id=task.task_id,
                answer=sub_context.clarification_question
                or "当前 Agent 没有匹配到可执行的业务技能，暂不继续调用工具。请补充更明确的业务场景或联系管理员配置对应 Skill。",
                confidence=0.2,
                risk_level="low",
                metadata={
                    "no_skill_blocked": True,
                    "no_skill_policy": sub_context.no_skill_policy,
                    "clarification_source": "skill_selection",
                    "skill_selection_fallback": sub_context.skill_selection_fallback,
                    "skill_selection_source": sub_context.skill_selection_source,
                    "skill_selection_decision_trace": task.metadata.get("skill_selection_decision_trace"),
                },
                selected_skill_id=sub_context.selected_skill_id,
                selected_skill_metadata=sub_context.selected_skill_metadata,
                skill_selection_score=sub_context.skill_selection_score,
                skill_selection_reason=sub_context.skill_selection_reason,
            )
        if self.use_tool_calling_runner and self.tool_calling_runner is not None:
            self._log_runner_started(task)
            """Construct the context for the LLM, including the task, skill, knowledge hints, 
            conversation summary, and other relevant information."""
            messages = self.build_messages(
                task=task,
                parent_context=parent_context,
                sub_context=sub_context,
                agent_card=agent_card,
            )
            principal = principal_dict_from_auth_context(task.auth_context)
            tool_schemas = self.get_available_tool_schemas(agent_card, principal=principal)
            """LLM 工具循环"""
            run_result = await self.tool_calling_runner.run(
                agent_name=self.name,
                messages=messages,
                tools=tool_schemas,
                session_key=task.session_key,
                request_id=str(task.request_id or task.task_id or ""),
                trace_id=task.trace_id,
                agent_card=agent_card,
                principal=principal,
                auth_context=task.auth_context,
            )
            result = self.build_result_from_runner(
                task=task,
                sub_context=sub_context,
                agent_card=agent_card,
                run_result=run_result,
            )
            result = self._enforce_tool_evidence_requirement(
                task=task,
                sub_context=sub_context,
                run_result=run_result,
                result=result,
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

    def get_agent_card(self, task: SubAgentTask) -> AgentCard:
        """Load the trusted AgentCard and verify the task targets this agent/version."""
        if task.agent_name != self.name:
            raise ValueError(f"task targets {task.agent_name}, but this runtime is {self.name}")
        agent_card = self.agent_card_loader.get_agent_card(task.agent_name)
        if agent_card is None or not agent_card.enabled:
            raise ValueError(f"enabled AgentCard not found for {task.agent_name}")
        if agent_card.version != task.agent_card_version:
            raise ValueError(
                f"AgentCard version mismatch for {task.agent_name}: "
                f"task={task.agent_card_version}, runtime={agent_card.version}"
            )
        return agent_card

    def get_available_tool_names(self, agent_card: AgentCard) -> list[str]:
        if self.tool_executor is None:
            return agent_card.private_tools
        return self.tool_executor.registry.list_available_tools_for_agent(self.name, agent_card)

    def get_available_tool_schemas(self, agent_card: AgentCard, principal: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.tool_executor is None:
            return []
        return self.tool_executor.registry.list_tools_for_agent(
            agent_card,
            principal=principal,
            authorization_service=getattr(self.tool_executor, "authorization_service", None),
        )

    async def call_tool(
        self,
        *,
        task: SubAgentTask,
        agent_card: AgentCard,
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
            request_id=task.request_id,
            trace_id=task.trace_id,
            session_key=task.session_key,
            principal=principal_dict_from_auth_context(task.auth_context),
            auth_context=task.auth_context,
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
                "content": self.prompt_loader.render(
                    "subagent_reasoning/system.md",
                    agent_name=agent_card.agent_name,
                    agent_description=agent_card.description,
                    skill_content=sub_context.skill_content,
                    requires_tool_evidence=str(self._requires_tool_evidence(sub_context)).lower(),
                ),
            },
            {
                "role": "user",
                "content": self.prompt_loader.render(
                    "subagent_reasoning/user.md",
                    original_query=task.original_query,
                    rewritten_query=sub_context.rewritten_query,
                    intent=task.intent,
                    entities=task.entities,
                    short_summary=parent_context.short_summary or "",
                    lightweight_hints=parent_context.lightweight_knowledge_hints,
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
            diagnosis=None,
            evidence=evidence,
            tool_calls=run_result.tool_calls,
            recommendation=None,
            responsibility=None,
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
                },
                "skill_selection_source": sub_context.skill_selection_source,
                "skill_selection_fallback": sub_context.skill_selection_fallback,
                "skill_selection_decision_trace": task.metadata.get("skill_selection_decision_trace"),
            },
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )

    def _enforce_tool_evidence_requirement(
        self,
        *,
        task: SubAgentTask,
        sub_context: SubAgentContext,
        run_result: ToolCallingRunResult,
        result: SubAgentResult,
    ) -> SubAgentResult:
        """Prevent evidence-required Skills from returning an ungrounded final answer."""
        if not self._requires_tool_evidence(sub_context) or result.needs_human_approval:
            return result
        if self._has_successful_tool_result(run_result):
            return result

        missing_tool_arguments = self._missing_tool_arguments(run_result)
        if not missing_tool_arguments and run_result.stopped_reason != "final":
            return result

        skill_name = str((sub_context.selected_skill_metadata or {}).get("name") or sub_context.selected_skill_id or "当前业务")
        labels = self._missing_argument_labels(missing_tool_arguments)
        if labels:
            question = f"要继续{skill_name}，请补充：{'、'.join(labels)}。"
        else:
            question = f"要继续{skill_name}，需要先获取有效的业务查询结果。请补充相关业务编号或明确查询条件后重试。"

        metadata = {
            **result.metadata,
            "clarification": True,
            "clarification_source": "tool_evidence_required",
            "clarification_question": question,
            "missing_required_entities": [],
            "missing_tool_arguments": missing_tool_arguments,
            "tool_evidence_required": True,
            "tool_evidence_satisfied": False,
        }
        log_event(
            "tool_evidence_required_clarification",
            request_id=task.request_id,
            trace_id=task.trace_id,
            session_key=task.session_key,
            node=self.name,
            message="Skill requires tool evidence but no successful tool result was available",
            data={
                "selected_skill_id": sub_context.selected_skill_id,
                "stopped_reason": run_result.stopped_reason,
                "missing_tool_arguments": missing_tool_arguments,
            },
        )
        return result.model_copy(
            update={
                "answer": question,
                "confidence": 0.4,
                "risk_level": "low",
                "metadata": metadata,
            }
        )

    @staticmethod
    def _requires_tool_evidence(sub_context: SubAgentContext) -> bool:
        return bool((sub_context.selected_skill_metadata or {}).get("requires_tool_evidence"))

    @staticmethod
    def _has_successful_tool_result(run_result: ToolCallingRunResult) -> bool:
        return any(item.get("success") is True for item in run_result.tool_calls if isinstance(item, dict))

    @staticmethod
    def _missing_tool_arguments(run_result: ToolCallingRunResult) -> list[dict[str, Any]]:
        missing_by_tool: dict[str, list[str]] = {}
        for item in run_result.tool_calls:
            if not isinstance(item, dict):
                continue
            arguments = item.get("missing_required_arguments")
            if not isinstance(arguments, list) or not arguments:
                continue
            tool_name = str(item.get("name") or item.get("tool_name") or "unknown_tool")
            values = missing_by_tool.setdefault(tool_name, [])
            for argument in arguments:
                name = str(argument)
                if name and name not in values:
                    values.append(name)
        return [
            {"tool_name": tool_name, "arguments": arguments}
            for tool_name, arguments in missing_by_tool.items()
        ]

    def _missing_argument_labels(self, missing_tool_arguments: list[dict[str, Any]]) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for item in missing_tool_arguments:
            tool_name = str(item.get("tool_name") or "")
            definition = self.tool_executor.registry.get_definition(tool_name) if self.tool_executor is not None else None
            properties = definition.parameters.get("properties", {}) if definition and isinstance(definition.parameters, dict) else {}
            for argument in item.get("arguments") or []:
                argument_name = str(argument)
                schema = properties.get(argument_name, {}) if isinstance(properties, dict) else {}
                description = schema.get("description") if isinstance(schema, dict) else None
                label = str(description or argument_name)
                if label not in seen:
                    seen.add(label)
                    labels.append(label)
        return labels

    def _tool_call_to_evidence(self, item: dict[str, Any]) -> dict[str, Any]:
        tool_name = str(item.get("name") or item.get("tool_name") or "")
        mapping = {
            "query_internal_log": ("internal_log", "query_internal_log"),
            "rag_search_tool": ("knowledge", "KnowledgeService"),
            "mcp.workflow.query_refund_task": ("mcp_workflow", "MCPClientManager"),
            "mcp.logs.query_trace": ("mcp_logs", "MCPClientManager"),
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

    def _log_runner_started(self, task: SubAgentTask) -> None:
        event_name = "troubleshooting_started" if self.name == "troubleshooting_agent" else "subagent_started"
        log_event(
            event_name,
            request_id=str(task.request_id or ""),
            trace_id=str(task.trace_id or ""),
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
            request_id=str(task.request_id or ""),
            trace_id=str(task.trace_id or ""),
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
        agent_card: AgentCard,
    ) -> SubAgentResult:
        """Execute task-specific logic."""
