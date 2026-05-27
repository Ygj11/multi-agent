from __future__ import annotations

"""变更影响分析子 Agent。"""

from typing import Any

from pydantic import BaseModel, Field

from app.observability.logger import log_event, preview_text
from app.runtime.context_builder import ContextBuilder
from app.schemas.agent_card import AgentCard
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.tools.executor import ToolExecutor


class ChangeImpactInput(BaseModel):
    """变更影响分析输入 schema。"""

    change_description: str
    session_key: str
    request_id: str | None = None
    trace_id: str | None = None


class ChangeImpactOutput(BaseModel):
    """变更影响分析输出 schema。"""

    change_type: str
    affected_interfaces: list[str] = Field(default_factory=list)
    affected_fields: list[str] = Field(default_factory=list)
    affected_subagents: list[str] = Field(default_factory=list)
    affected_tools: list[str] = Field(default_factory=list)
    recommended_tests: list[str] = Field(default_factory=list)
    summary: str


class ChangeImpactAnalysisAgent:
    """分析接口字段、错误码、签名规则或知识文档变更的影响范围。"""

    name = "change_impact_analysis_agent"

    def __init__(
        self,
        context_builder: ContextBuilder,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """Store ContextBuilder and ToolExecutor dependencies."""
        self.context_builder = context_builder
        self.tool_executor = tool_executor

    async def run(self, task: SubAgentTask, parent_context: OrchestratorContext) -> SubAgentResult:
        """执行变更影响分析。"""
        request_id = str(task.metadata.get("request_id") or "")
        trace_id = str(task.metadata.get("trace_id") or "")
        log_event(
            "subagent_selected",
            request_id=request_id,
            trace_id=trace_id,
            session_key=task.session_key,
            node=self.name,
            message="Change impact analysis agent running",
            data={"query_preview": preview_text(task.query)},
        )
        agent_card = self._card_from_task(task)
        sub_context = await self.context_builder.build_for_subagent(
            task=task,
            parent_context=parent_context,
            allowed_tools=["get_knowledge"],
        )
        output = self._analyze(
            ChangeImpactInput(
                change_description=task.query,
                session_key=task.session_key,
                request_id=request_id or None,
                trace_id=trace_id or None,
            )
        )
        knowledge_result = await self._call_tool(
            task=task,
            agent_card=agent_card,
            name="get_knowledge",
            arguments={"query": task.query, "top_k": 3, "selected_skill_id": sub_context.selected_skill_id},
        )
        evidence = [
            {
                "type": "change_impact",
                "source": self.name,
                "tool_name": None,
                "summary": output.summary,
                "result_preview": output.model_dump(),
                "confidence": 0.82,
            },
            {
                "type": "knowledge",
                "source": "get_knowledge",
                "tool_name": "get_knowledge",
                "summary": preview_text(str(knowledge_result.result or knowledge_result.error)),
                "result_preview": {"success": knowledge_result.success, "content_preview": preview_text(str(knowledge_result.result))},
                "confidence": 0.72 if knowledge_result.success else 0.25,
            },
        ]
        answer = (
            f"变更影响分析完成：{output.summary}"
            f"影响接口：{', '.join(output.affected_interfaces) or '待确认'}。"
            f"影响字段：{', '.join(output.affected_fields) or '待确认'}。"
            f"关联工具：{', '.join(output.affected_tools) or '无'}。"
            f"建议测试：{', '.join(output.recommended_tests)}。"
        )
        return SubAgentResult(
            name=self.name,
            agent_name=self.name,
            task_id=task.task_id,
            answer=answer,
            diagnosis=output.summary,
            evidence=evidence,
            tool_calls=[knowledge_result.model_dump()],
            recommendation="请优先补充契约测试、签名回归测试和渠道联调样例，再同步知识库文档。",
            responsibility="接口提供方负责变更说明和兼容策略，渠道方负责按新规则完成适配。",
            confidence=0.84,
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )

    async def _call_tool(self, *, task: SubAgentTask, agent_card: AgentCard | None, name: str, arguments: dict[str, Any]):
        if self.tool_executor is not None:
            return await self.tool_executor.execute(
                agent_name=self.name,
                tool_name=name,
                arguments=arguments,
                agent_card=agent_card,
                request_id=str(task.metadata.get("request_id") or ""),
                trace_id=str(task.metadata.get("trace_id") or ""),
                session_key=task.session_key,
            )
        raise RuntimeError("tool executor is not configured")

    @staticmethod
    def _card_from_task(task: SubAgentTask) -> AgentCard | None:
        data = task.metadata.get("agent_card")
        return AgentCard(**data) if isinstance(data, dict) else None

    @staticmethod
    def _analyze(payload: ChangeImpactInput) -> ChangeImpactOutput:
        """用关键词规则形成第一阶段影响面，后续可替换真实变更分析服务。"""
        text = payload.change_description
        affected_interfaces: list[str] = []
        affected_fields: list[str] = []
        affected_tools = ["get_knowledge"]
        affected_subagents = ["troubleshooting_agent", "document_parse_agent"]
        recommended_tests = ["知识库命中测试", "多轮问答回归测试"]

        if "submitProposal" in text or "投保" in text or "签名" in text or "timestamp" in text:
            affected_interfaces.append("submitProposal")
        if "timestamp" in text:
            affected_fields.append("timestamp")
        if "错误码" in text or "E102" in text:
            change_type = "error_code_change"
            recommended_tests.append("E102 错误码解释回归测试")
        elif "签名" in text or "timestamp" in text:
            change_type = "signature_rule_change"
            affected_tools.extend(["query_internal_log", "mcp.workflow.query_refund_task"])
            recommended_tests.extend(["签名 base string 回归测试", "渠道侧 timestamp 参与签名联调测试"])
        elif "字段" in text:
            change_type = "field_change"
            recommended_tests.append("接口字段兼容性测试")
        else:
            change_type = "knowledge_document_change"
            recommended_tests.append("知识文档摘要一致性测试")

        summary = f"识别为 {change_type}，重点影响 {', '.join(affected_interfaces) or '相关接口'} 的联调、知识检索和排障链路。"
        return ChangeImpactOutput(
            change_type=change_type,
            affected_interfaces=affected_interfaces,
            affected_fields=affected_fields,
            affected_subagents=affected_subagents,
            affected_tools=sorted(set(affected_tools)),
            recommended_tests=recommended_tests,
            summary=summary,
        )
