from __future__ import annotations

"""任务完成度验收证据收集器。

Verifier 不能直接执行业务工具，因此它必须依赖这里收集到的只读证据来判断任务
是否完成。证据来源包括子 Agent 返回的轻量 evidence、EvidenceStore 中持久化的
工具摘要，以及可选的只读状态探针。
"""

import hashlib
import json
from typing import Any

from app.evidence.store import EvidenceStore
from app.skills.catalog import SkillCatalog
from app.verification.task_completion.schemas import (
    TaskCompletionVerificationContext,
    VerificationEvidence,
)
from app.verification.task_completion.state_probes.base import BusinessStateProbe


class VerificationEvidenceCollector:
    """把子 Agent 执行结果整理成 Verifier 可读的轻量证据上下文。

    这里同时重新加载完整 Skill.md，因为 Skill SOP 是执行和验收的共同业务依据。
    完整 Skill 文本只进入本次 Verifier prompt，不作为长期 Graph State 字段保存。
    """

    def __init__(
        self,
        *,
        skill_catalog: SkillCatalog,
        evidence_store: EvidenceStore | None = None,
        probes: list[BusinessStateProbe] | None = None,
        enable_state_probes: bool = True,
    ) -> None:
        self.skill_catalog = skill_catalog
        self.evidence_store = evidence_store
        self.probes = probes or []
        self.enable_state_probes = enable_state_probes

    async def collect(self, state: dict[str, Any]) -> tuple[TaskCompletionVerificationContext, str | None]:
        """从 Graph State 生成 TaskCompletionVerificationContext。

        这个 context 是 Runtime Verify Loop 的“验收包”：包含用户任务、改写任务、
        解析实体、原 selected_agent/selected_skill_id、完整 Skill、子 Agent 回答、
        工具调用摘要、证据摘要、repair 历史和停止原因。
        """
        selected_skill_id = str(state.get("selected_skill_id") or "")
        # Verifier 必须按第一次选中的 Skill 验收，不能重新选择 Skill 或只看 metadata。
        skill = self.skill_catalog.load_skill_content(selected_skill_id)
        selected_skill_version = self._skill_version(skill.content)
        subagent_result = state.get("subagent_result") if isinstance(state.get("subagent_result"), dict) else {}
        tool_calls = list(subagent_result.get("tool_calls") or [])
        # 子 Agent 返回的 evidence 是最近一轮执行的即时摘要；EvidenceStore 是
        # ToolExecutor 持久化出来的可审计摘要，两者合并给 Verifier 交叉判断。
        evidence = self._evidence_from_subagent_result(subagent_result)
        evidence.extend(await self._evidence_from_store(state))

        context = TaskCompletionVerificationContext(
            request_id=state.get("request_id"),
            trace_id=state.get("trace_id"),
            session_key=str(state.get("session_key") or ""),
            original_query=str(state.get("original_query") or ""),
            rewritten_query=str(state.get("rewritten_query") or state.get("original_query") or ""),
            entities=state.get("entities") if isinstance(state.get("entities"), dict) else {},
            selected_agent=str(state.get("selected_agent") or subagent_result.get("agent_name") or ""),
            selected_skill_id=selected_skill_id,
            selected_skill_version=selected_skill_version,
            skill_name=skill.metadata.name,
            skill_content=skill.content,
            answer=str(subagent_result.get("answer") or state.get("answer") or ""),
            tool_calls=tool_calls,
            evidence=evidence,
            stopped_reason=self._stopped_reason(subagent_result),
            repair_round=int(state.get("repair_round") or 0),
            repair_history=list(state.get("repair_history") or []),
            original_subagent_result=state.get("original_subagent_result") if isinstance(state.get("original_subagent_result"), dict) else {},
            previous_subagent_results=list(state.get("previous_subagent_results") or []),
            auth_context=state.get("auth_context") if isinstance(state.get("auth_context"), dict) else None,
        )
        if self.enable_state_probes:
            # 状态探针只做只读验证，例如查询最终业务状态；它不是原任务工具执行入口。
            context.evidence.extend(await self._probe_evidence(context))
        return context, selected_skill_version

    async def _evidence_from_store(self, state: dict[str, Any]) -> list[VerificationEvidence]:
        """把 EvidenceStore 中的持久化证据转成 Verifier 可读摘要。

        Store 中只保存 summary 和 tool_log_id，不把完整工具原文塞进 prompt；
        Verifier 需要的是“足以判断任务完成度的摘要”，不是无限制读取原始结果。
        """
        if self.evidence_store is None or not state.get("request_id"):
            return []
        items = await self.evidence_store.list_by_request(str(state["request_id"]))
        return [
            VerificationEvidence(
                evidence_id=item.evidence_id,
                source_type=item.source_type,
                source_name=item.source_name,
                summary=item.summary or f"{item.source_type}:{item.source_name}",
                status="available",
                tool_name=item.metadata.get("tool_name") if isinstance(item.metadata, dict) else None,
                result_summary={"preview": item.summary or "", "tool_log_id": item.tool_log_id},
                metadata={"created_at": item.created_at, "tool_log_id": item.tool_log_id, **item.metadata},
            )
            for item in items
        ]

    @staticmethod
    def _evidence_from_subagent_result(subagent_result: dict[str, Any]) -> list[VerificationEvidence]:
        """读取子 Agent 本轮返回的轻量 evidence。

        这类 evidence 主要服务于“本轮工具是否产生了有效观察”。它不能替代
        ToolExecutor 的持久化日志，只是 Verifier prompt 中更短、更好读的摘要。
        """
        result: list[VerificationEvidence] = []
        for item in subagent_result.get("evidence") or []:
            if not isinstance(item, dict):
                continue
            result.append(
                VerificationEvidence(
                    evidence_id=item.get("evidence_id") or item.get("id"),
                    source_type=str(item.get("type") or "tool"),
                    source_name=str(item.get("source") or item.get("tool_name") or "subagent"),
                    summary=str(item.get("summary") or item.get("result_preview") or "")[:500],
                    status="success" if float(item.get("confidence") or 0) >= 0.5 else "available",
                    tool_name=item.get("tool_name"),
                    result_summary={"preview": str(item.get("result_preview") or "")[:500]},
                    metadata={"confidence": item.get("confidence")},
                )
            )
        return result

    async def _probe_evidence(self, context: TaskCompletionVerificationContext) -> list[VerificationEvidence]:
        """运行可选的只读业务状态探针。

        对写操作或异步状态变更，不能只相信“工具调用 success=true”；状态探针可以
        提供最终业务状态证据。探针失败时应返回 unavailable 证据，而不是认定成功。
        """
        evidence: list[VerificationEvidence] = []
        for probe in self.probes:
            if await probe.supports(context):
                evidence.extend(await probe.collect(context))
        return evidence

    @staticmethod
    def _stopped_reason(subagent_result: dict[str, Any]) -> str | None:
        metadata = subagent_result.get("metadata") if isinstance(subagent_result.get("metadata"), dict) else {}
        runner = metadata.get("tool_calling_runner") if isinstance(metadata.get("tool_calling_runner"), dict) else {}
        value = runner.get("stopped_reason")
        return str(value) if value else None

    @staticmethod
    def _skill_version(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _preview(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, default=str)[:500]
        except TypeError:
            return str(value)[:500]
