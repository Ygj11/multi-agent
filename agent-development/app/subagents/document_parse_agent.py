from __future__ import annotations

"""文档解析子 Agent。"""

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from app.observability.logger import log_event, preview_text
from app.runtime.context_builder import ContextBuilder
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.tools.broker import ToolBroker
from app.tools.executor import ToolExecutor


class DocumentParseInput(BaseModel):
    """文档解析输入 schema。"""

    content: str
    content_type: str = "text"


class DocumentParseOutput(BaseModel):
    """文档解析输出 schema。"""

    content_type: str
    title: str | None = None
    interfaces: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)
    summary: str


class DocumentParseAgent:
    """解析 markdown、text、json、yaml 形式的轻量文档内容。"""

    name = "document_parse_agent"

    def __init__(
        self,
        context_builder: ContextBuilder,
        tool_broker: ToolBroker | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """保留 ToolBroker 依赖，后续 OCR、PDF 或文档服务工具接入时继续走统一通道。"""
        self.context_builder = context_builder
        self.tool_broker = tool_broker
        self.tool_executor = tool_executor

    async def run(self, task: SubAgentTask, parent_context: OrchestratorContext) -> SubAgentResult:
        """执行文档解析并返回统一 SubAgentResult。"""
        request_id = str(task.metadata.get("request_id") or "")
        trace_id = str(task.metadata.get("trace_id") or "")
        log_event(
            "subagent_selected",
            request_id=request_id,
            trace_id=trace_id,
            session_key=task.session_key,
            node=self.name,
            message="Document parse agent running",
            data={"query_preview": preview_text(task.query)},
        )
        sub_context = await self.context_builder.build_for_subagent(
            task=task,
            parent_context=parent_context,
            allowed_tools=[],
        )
        parsed = self._parse(DocumentParseInput(content=task.original_query, content_type=self._detect_type(task.original_query)))
        evidence = [
            {
                "type": "document_parse",
                "source": self.name,
                "tool_name": None,
                "summary": parsed.summary,
                "result_preview": parsed.model_dump(),
                "confidence": 0.78,
            }
        ]
        answer = (
            f"文档解析完成：类型 {parsed.content_type}。"
            f"标题：{parsed.title or '未识别'}。"
            f"接口：{', '.join(parsed.interfaces) or '未识别'}。"
            f"字段：{', '.join(parsed.fields) or '未识别'}。"
            f"错误码：{', '.join(parsed.error_codes) or '未识别'}。"
            f"摘要：{parsed.summary}"
        )
        return SubAgentResult(
            name=self.name,
            agent_name=self.name,
            task_id=task.task_id,
            answer=answer,
            diagnosis=parsed.summary,
            evidence=evidence,
            recommendation="建议将解析出的接口、字段和错误码纳入后续联调用例与知识库校验。",
            responsibility="文档解析 Agent 负责结构化提取，业务方负责确认字段含义和版本有效性。",
            confidence=0.78,
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )

    @staticmethod
    def _detect_type(content: str) -> str:
        """根据内容特征粗略判断文档类型。"""
        stripped = content.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return "json"
        if re.search(r"(?m)^\s*[\w.-]+\s*:", content):
            return "yaml"
        if "#" in content or "|" in content or "```" in content:
            return "markdown"
        return "text"

    @classmethod
    def _parse(cls, payload: DocumentParseInput) -> DocumentParseOutput:
        """解析轻量文档内容，当前不接 PDF、Word 或真实文档解析服务。"""
        content = payload.content
        interfaces = sorted(set(re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]*(?:Proposal|Policy|Trace|Sign)\b", content)))
        fields = cls._extract_fields(content)
        error_codes = sorted(set(re.findall(r"\bE\d{3,}\b", content)))
        title = cls._extract_title(content)
        if payload.content_type == "json":
            fields.extend(cls._extract_json_keys(content))
            fields = sorted(set(fields))
        summary = (
            f"识别到 {len(interfaces)} 个接口、{len(fields)} 个字段、{len(error_codes)} 个错误码；"
            "第一阶段仅支持 markdown/text/json/yaml 文本内容。"
        )
        return DocumentParseOutput(
            content_type=payload.content_type,
            title=title,
            interfaces=interfaces,
            fields=fields,
            error_codes=error_codes,
            summary=summary,
        )

    @staticmethod
    def _extract_title(content: str) -> str | None:
        """提取 markdown 标题或第一行短标题。"""
        markdown_title = re.search(r"(?m)^#\s+(.+)$", content)
        if markdown_title:
            return markdown_title.group(1).strip()
        first_line = content.strip().splitlines()[0] if content.strip() else ""
        return first_line[:80] if first_line else None

    @staticmethod
    def _extract_fields(content: str) -> list[str]:
        """从常见中文字段描述或 YAML 键中提取字段名。"""
        fields: set[str] = set()
        for match in re.finditer(r"(?:字段|fields?)[:：]\s*([^\n。；;]+)", content, flags=re.IGNORECASE):
            for part in re.split(r"[,，、\s]+", match.group(1)):
                if part and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", part):
                    fields.add(part)
        for key in re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", content):
            fields.add(key)
        return sorted(fields)

    @staticmethod
    def _extract_json_keys(content: str) -> list[str]:
        """提取 JSON 顶层和嵌套 key，用于最小可用的结构化提示。"""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return []

        keys: set[str] = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    keys.add(str(key))
                    walk(nested)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(data)
        return sorted(keys)
