from __future__ import annotations

"""问题排查子 Agent。"""

import re
from typing import Any

from app.observability.logger import log_event, preview_text
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.schemas.tool import ToolCall
from app.runtime.context_builder import ContextBuilder
from app.tools.broker import ToolBroker


class TroubleshootingAgent:
    """负责健康险接口联调问题排查的任务级执行单元。"""

    name = "troubleshooting_agent"

    def __init__(self, context_builder: ContextBuilder, tool_broker: ToolBroker) -> None:
        """注入 ContextBuilder 和 ToolBroker，确保工具调用受控。"""
        self.context_builder = context_builder
        self.tool_broker = tool_broker

    async def run(self, task: SubAgentTask, parent_context: OrchestratorContext) -> SubAgentResult:
        """执行问题排查任务，并返回结构化结果。"""
        trace_id = str(task.metadata.get("trace_id") or "")
        inbound_request_id = str(task.metadata.get("request_id") or "")
        log_event(
            "troubleshooting_started",
            request_id=inbound_request_id,
            trace_id=trace_id,
            session_key=task.session_key,
            node="troubleshooting_agent",
            message="Troubleshooting started",
            data={"request_id_in_task": self._find_request_id(task.query), "query_preview": preview_text(task.query)},
        )
        sub_context = await self.context_builder.build_for_subagent(
            task=task,
            parent_context=parent_context,
            allowed_tools=["query_internal_log", "get_knowledge", "partner_trace.get_request_detail"],
        )

        request_id = self._find_request_id(task.query) or self._find_request_id(parent_context.short_summary or "")
        evidence: list[dict[str, Any]] = []

        log_result = None
        if request_id:
            # 内部日志查询也必须经过 ToolBroker 和 PolicyGate。
            tool_result = await self.tool_broker.call(
                ToolCall(
                    name="query_internal_log",
                    arguments={"request_id": request_id, "selected_skill_id": sub_context.selected_skill_id},
                    request_id=inbound_request_id,
                    trace_id=trace_id,
                    session_key=task.session_key,
                )
            )
            log_result = tool_result.result if tool_result.success else None
            evidence.append(
                self._build_internal_log_evidence(
                    result=log_result,
                    error=tool_result.error,
                )
            )

        knowledge_result = await self.tool_broker.call(
            ToolCall(
                name="get_knowledge",
                arguments={"query": sub_context.rewritten_query, "top_k": 3, "selected_skill_id": sub_context.selected_skill_id},
                request_id=inbound_request_id,
                trace_id=trace_id,
                session_key=task.session_key,
            )
        )
        evidence.append(
            self._build_knowledge_evidence(
                result=knowledge_result.result,
                error=knowledge_result.error,
            )
        )

        partner_trace = None
        if self._should_query_partner_trace(request_id=request_id, log_result=log_result, parent_context=parent_context):
            trace_result = await self.tool_broker.call(
                ToolCall(
                    name="partner_trace.get_request_detail",
                    arguments={"request_id": request_id, "selected_skill_id": sub_context.selected_skill_id},
                    request_id=inbound_request_id,
                    trace_id=trace_id,
                    session_key=task.session_key,
                )
            )
            partner_trace = trace_result.result if trace_result.success else None
            evidence.append(
                self._build_partner_trace_evidence(
                    result=partner_trace,
                    error=trace_result.error,
                )
            )

        diagnosis, responsibility, recommendation = self._build_structured_result(
            request_id=request_id,
            log_result=log_result,
            partner_trace=partner_trace,
        )
        log_event(
            "evidence_built",
            request_id=inbound_request_id,
            trace_id=trace_id,
            session_key=task.session_key,
            node="troubleshooting_agent",
            message="Troubleshooting evidence built",
            data={
                "tool_sequence": [item.get("tool_name") for item in evidence],
                "evidence_count": len(evidence),
                "evidence_types": [item.get("type") for item in evidence],
                "diagnosis_preview": preview_text(diagnosis),
                "responsibility_preview": preview_text(responsibility),
            },
        )
        answer = self._build_answer(
            request_id=request_id,
            log_result=log_result,
            knowledge=str(knowledge_result.result or sub_context.mock_knowledge_hint),
            partner_trace=partner_trace,
            skill=sub_context.skill_content,
            parent_context=parent_context,
        )
        return SubAgentResult(
            name=self.name,
            answer=answer,
            diagnosis=diagnosis,
            evidence=evidence,
            recommendation=recommendation,
            responsibility=responsibility,
            confidence=0.9,
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )

    @staticmethod
    def _find_request_id(text: str) -> str | None:
        """从任务文本或摘要中提取 requestId。"""
        match = re.search(r"\bREQ_\d+\b", text)
        return match.group(0) if match else None

    @staticmethod
    def _should_query_partner_trace(
        *,
        request_id: str | None,
        log_result: dict[str, Any] | None,
        parent_context: OrchestratorContext,
    ) -> bool:
        """判断是否需要查询渠道侧 trace。"""
        if not request_id:
            return False
        if not log_result or not log_result.get("found"):
            return True
        if log_result.get("error_code") == "E102":
            return True
        suspected_reason = str(log_result.get("suspected_reason", ""))
        return "partner" in suspected_reason or "timestamp" in suspected_reason or "渠道" in parent_context.original_query

    @staticmethod
    def _build_answer(
        *,
        request_id: str | None,
        log_result: dict[str, Any] | None,
        knowledge: str,
        partner_trace: dict[str, Any] | None,
        skill: str,
        parent_context: OrchestratorContext,
    ) -> str:
        """根据日志、知识和上下文生成面向用户的排查建议。"""
        if log_result and log_result.get("found"):
            suspected_reason = log_result.get("suspected_reason", "")
            trace_summary = TroubleshootingAgent._format_trace_summary(partner_trace)
            ownership = TroubleshootingAgent._infer_ownership(suspected_reason, partner_trace)

            return (
                f"内部日志证据：{log_result['request_id']} 在 {log_result['interface_name']} 返回 E102，"
                f"错误含义是签名校验失败；我方签名规则版本为 {log_result['signature_rule_version']}，"
                f"server_sign={log_result['server_sign']}，partner_sign={log_result['partner_sign']}，"
                f"疑似原因是 {suspected_reason}。"
                f"知识库依据：{knowledge}"
                f"渠道侧 trace 证据：{trace_summary}"
                f"初步问题归属：{ownership}。"
                "建议处理动作：双方核对签名 base string、timestamp 是否参与签名和是否过期、"
                "secret/密钥版本、字段排序、空值字段处理以及 body 序列化方式。"
            )

        if request_id:
            trace_summary = TroubleshootingAgent._format_trace_summary(partner_trace)
            return (
                f"未查询到 {request_id} 的模拟日志，但 E102 通常表示签名校验失败。"
                f"知识库依据：{knowledge}"
                f"渠道侧 trace 证据：{trace_summary}"
                "建议先补充完整错误报文和渠道请求原文，再检查 timestamp 是否参与签名、密钥版本、字段排序、"
                "空值字段和 body 序列化方式。"
            )

        if parent_context.short_summary and "E102" in parent_context.short_summary:
            return (
                "结合上一轮上下文，这个问题仍指向 E102 签名校验失败。一般需要先比较我方验签规则和渠道方签名原文，"
                "重点看 timestamp 是否参与签名、密钥版本是否一致、字段排序是否一致。若渠道仍使用旧版签名规则，"
                "通常更偏向渠道方适配问题；若 timestamp 过期，则需要检查时间窗口和重放策略。"
            )

        return (
            "当前没有明确 requestId。按照 troubleshooting skill，E102 签名校验失败应先查内部日志，"
            "再检查签名字段排序、timestamp、密钥版本、空值字段、body 序列化以及渠道方是否使用旧版签名规则。"
        )

    @staticmethod
    def _build_internal_log_evidence(result: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
        """构造内部日志结构化证据。"""
        if result and result.get("found"):
            summary = (
                f"内部日志显示 {result.get('request_id')} 在 {result.get('interface_name')} 返回 "
                f"{result.get('error_code')}，疑似原因是 {result.get('suspected_reason')}。"
            )
            preview = {
                "request_id": result.get("request_id"),
                "error_code": result.get("error_code"),
                "interface_name": result.get("interface_name"),
                "signature_rule_version": result.get("signature_rule_version"),
            }
            confidence = 0.9
        else:
            summary = error or "内部日志未命中。"
            preview = result or {}
            confidence = 0.3
        return {
            "type": "internal_log",
            "source": "query_internal_log",
            "tool_name": "query_internal_log",
            "summary": summary,
            "result_preview": preview,
            "confidence": confidence,
        }

    @staticmethod
    def _build_knowledge_evidence(result: Any, error: str | None) -> dict[str, Any]:
        """构造知识库结构化证据。"""
        content = str(result or error or "知识库未命中。")
        return {
            "type": "knowledge",
            "source": "InMemoryKnowledgeService",
            "tool_name": "get_knowledge",
            "summary": content[:180],
            "result_preview": {"content_preview": content[:240]},
            "confidence": 0.75 if result else 0.2,
        }

    @staticmethod
    def _build_partner_trace_evidence(result: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
        """构造渠道侧 trace 结构化证据。"""
        if result and result.get("found"):
            summary = str(result.get("summary", "渠道侧 trace 已命中。"))
            preview = {
                "request_id": result.get("request_id"),
                "partner": result.get("partner"),
                "trace_source": result.get("trace_source"),
                "partner_signature_rule_version": result.get("partner_signature_rule_version"),
                "timestamp_included_in_sign": result.get("timestamp_included_in_sign"),
                "timestamp_status": result.get("timestamp_status"),
            }
            confidence = 0.88
        else:
            summary = error or (result or {}).get("message", "未查询到渠道侧 trace。")
            preview = result or {}
            confidence = 0.25
        return {
            "type": "partner_trace",
            "source": "FakeMCPConnector",
            "tool_name": "partner_trace.get_request_detail",
            "summary": summary,
            "result_preview": preview,
            "confidence": confidence,
        }

    @staticmethod
    def _build_structured_result(
        *,
        request_id: str | None,
        log_result: dict[str, Any] | None,
        partner_trace: dict[str, Any] | None,
    ) -> tuple[str, str, str]:
        """生成 diagnosis、responsibility、recommendation 三个结构化字段。"""
        if log_result and log_result.get("found"):
            diagnosis = (
                f"{request_id} 返回 E102，诊断为签名校验失败。"
                f"内部日志疑似原因：{log_result.get('suspected_reason')}。"
            )
        elif request_id:
            diagnosis = f"{request_id} 未命中内部日志，但仍按 E102 签名校验失败方向排查。"
        else:
            diagnosis = "缺少 requestId，当前只能给出 E102 签名校验失败的通用排查建议。"

        responsibility = TroubleshootingAgent._infer_ownership(
            str((log_result or {}).get("suspected_reason", "")),
            partner_trace,
        )
        recommendation = (
            "建议核对签名 base string、timestamp 是否参与签名和是否过期、"
            "secret/密钥版本、字段排序、空值字段处理以及 body 序列化方式。"
        )
        return diagnosis, responsibility, recommendation

    @staticmethod
    def _format_trace_summary(partner_trace: dict[str, Any] | None) -> str:
        """格式化渠道侧 trace 证据。"""
        if not partner_trace:
            return "未获取到渠道侧 trace。"
        if not partner_trace.get("found"):
            return str(partner_trace.get("message", "未查询到渠道侧 trace。"))
        return str(partner_trace.get("summary", "渠道侧 trace 已查询但缺少摘要。"))

    @staticmethod
    def _infer_ownership(suspected_reason: str, partner_trace: dict[str, Any] | None) -> str:
        """结合内部日志和渠道 trace 判断初步归属。"""
        if partner_trace and partner_trace.get("found"):
            if partner_trace.get("timestamp_included_in_sign") is False:
                return "渠道侧 trace 显示仍使用旧版签名规则且 timestamp 未参与签名，初步更偏向渠道方适配问题"
            if partner_trace.get("timestamp_status") == "expired":
                return "渠道侧 trace 显示 timestamp 过期，初步更偏向渠道侧时间窗口或重放策略问题"
        if suspected_reason == "partner signature does not include timestamp":
            return "初步更偏向渠道方签名规则或签名原文生成问题"
        if suspected_reason == "timestamp expired":
            return "初步更偏向请求时间戳过期或双方时间窗口配置问题"
        return "需要继续结合渠道侧签名原文和我方验签规则确认问题归属"
