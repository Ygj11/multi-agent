from __future__ import annotations

"""合规安全子 Agent。"""

import re
from typing import Any

from pydantic import BaseModel, Field

from app.observability.logger import log_event, preview_text
from app.runtime.context_builder import ContextBuilder
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.tools.broker import ToolBroker


class ComplianceSecurityInput(BaseModel):
    """合规安全检查的输入 schema。"""

    text: str
    session_key: str
    request_id: str | None = None
    trace_id: str | None = None


class ComplianceFinding(BaseModel):
    """单个合规风险发现。"""

    category: str
    summary: str
    severity: str
    masked_preview: str


class ComplianceSecurityOutput(BaseModel):
    """合规安全检查的输出 schema。"""

    risk_level: str
    findings: list[ComplianceFinding] = Field(default_factory=list)
    recommendation: str
    can_send_external: bool


class ComplianceSecurityAgent:
    """检查文本中的隐私、敏感信息和外发风险。"""

    name = "compliance_security_agent"

    def __init__(self, context_builder: ContextBuilder, tool_broker: ToolBroker) -> None:
        """保留 ToolBroker 依赖，后续合规工具接入时仍走统一工具通道。"""
        self.context_builder = context_builder
        self.tool_broker = tool_broker

    async def run(self, task: SubAgentTask, parent_context: OrchestratorContext) -> SubAgentResult:
        """执行合规安全检查并返回结构化结论。"""
        request_id = str(task.metadata.get("request_id") or "")
        trace_id = str(task.metadata.get("trace_id") or "")
        log_event(
            "subagent_selected",
            request_id=request_id,
            trace_id=trace_id,
            session_key=task.session_key,
            node=self.name,
            message="Compliance security agent running",
            data={"query_preview": preview_text(task.query)},
        )
        sub_context = await self.context_builder.build_for_subagent(
            task=task,
            parent_context=parent_context,
            allowed_tools=[],
        )
        output = self._inspect(
            ComplianceSecurityInput(
                text=f"{task.original_query}\n{task.query}",
                session_key=task.session_key,
                request_id=request_id or None,
                trace_id=trace_id or None,
            )
        )
        evidence = [
            {
                "type": "compliance_finding",
                "source": self.name,
                "tool_name": None,
                "summary": finding.summary,
                "result_preview": finding.model_dump(),
                "confidence": 0.82 if finding.severity != "low" else 0.65,
            }
            for finding in output.findings
        ]
        answer = self._build_answer(output)
        return SubAgentResult(
            name=self.name,
            answer=answer,
            diagnosis=f"合规安全风险等级：{output.risk_level}",
            evidence=evidence,
            recommendation=output.recommendation,
            responsibility="由业务调用方在外发前完成脱敏、最小化字段和授权确认",
            confidence=0.86,
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )

    @classmethod
    def _inspect(cls, payload: ComplianceSecurityInput) -> ComplianceSecurityOutput:
        """使用轻量规则识别敏感信息，第一阶段不引入复杂 DLP 引擎。"""
        text = payload.text
        masked = cls._mask(text)
        findings: list[ComplianceFinding] = []
        if re.search(r"1[3-9]\d{9}", text):
            findings.append(
                ComplianceFinding(
                    category="phone",
                    summary="文本中包含手机号，外发前需要脱敏或确认必要性。",
                    severity="high",
                    masked_preview=preview_text(masked),
                )
            )
        if re.search(r"\d{17}[\dXx]", text):
            findings.append(
                ComplianceFinding(
                    category="id_card",
                    summary="文本中包含身份证号，属于高敏个人信息。",
                    severity="high",
                    masked_preview=preview_text(masked),
                )
            )
        if re.search(r"(?i)(secret|token|password|api[_-]?key)", text):
            findings.append(
                ComplianceFinding(
                    category="credential",
                    summary="文本中疑似包含密钥、token 或密码类凭据。",
                    severity="high",
                    masked_preview=preview_text(masked),
                )
            )
        if any(keyword in text for keyword in ("健康告知", "病史", "医疗记录", "诊断", "医保")):
            findings.append(
                ComplianceFinding(
                    category="health_data",
                    summary="文本中包含健康或医疗相关信息，外发需遵循最小必要原则。",
                    severity="medium",
                    masked_preview=preview_text(masked),
                )
            )

        if not findings:
            return ComplianceSecurityOutput(
                risk_level="low",
                findings=[
                    ComplianceFinding(
                        category="general",
                        summary="未发现明显手机号、身份证号、凭据或健康医疗敏感信息。",
                        severity="low",
                        masked_preview=preview_text(masked),
                    )
                ],
                recommendation="可以继续处理，但仍建议按最小必要原则保留业务字段。",
                can_send_external=True,
            )

        risk_level = "high" if any(item.severity == "high" for item in findings) else "medium"
        return ComplianceSecurityOutput(
            risk_level=risk_level,
            findings=findings,
            recommendation="外发前请删除或脱敏敏感字段，确认业务必要性、用户授权和接收方范围。",
            can_send_external=False,
        )

    @staticmethod
    def _mask(text: str) -> str:
        """生成脱敏预览，避免合规 Agent 在结果中泄露原始敏感值。"""
        text = re.sub(r"1[3-9]\d{9}", "***PHONE***", text)
        text = re.sub(r"\d{17}[\dXx]", "***ID_CARD***", text)
        text = re.sub(r"(?i)(secret|token|password|api[_-]?key)\s*[:=]\s*\S+", r"\1=***", text)
        return text

    @staticmethod
    def _build_answer(output: ComplianceSecurityOutput) -> str:
        """把结构化结果压缩成向用户展示的回答。"""
        finding_text = "；".join(item.summary for item in output.findings)
        external = "不建议直接外发" if not output.can_send_external else "可在最小必要原则下继续处理"
        return f"合规安全检查完成：风险等级 {output.risk_level}。发现：{finding_text}。结论：{external}。建议：{output.recommendation}"
