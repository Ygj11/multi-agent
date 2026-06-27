from __future__ import annotations

"""任务完成度验收证据收集器。"""

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
    """把子 Agent 执行结果整理成 Verifier 可读的轻量证据上下文。"""

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
        selected_skill_id = str(state.get("selected_skill_id") or "")
        skill = self.skill_catalog.load_skill_content(selected_skill_id)
        selected_skill_version = self._skill_version(skill.content)
        subagent_result = state.get("subagent_result") if isinstance(state.get("subagent_result"), dict) else {}
        tool_calls = list(subagent_result.get("tool_calls") or [])
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
            context.evidence.extend(await self._probe_evidence(context))
        return context, selected_skill_version

    async def _evidence_from_store(self, state: dict[str, Any]) -> list[VerificationEvidence]:
        if self.evidence_store is None or not state.get("request_id"):
            return []
        items = await self.evidence_store.list_by_request(str(state["request_id"]))
        return [
            VerificationEvidence(
                evidence_id=item.evidence_id,
                source_type=item.source_type,
                source_name=item.source_name,
                summary=item.summary or self._preview(item.content),
                status="available",
                tool_name=item.metadata.get("tool_name") if isinstance(item.metadata, dict) else None,
                result_summary={"preview": self._preview(item.content)},
                metadata={"created_at": item.created_at},
            )
            for item in items
        ]

    @staticmethod
    def _evidence_from_subagent_result(subagent_result: dict[str, Any]) -> list[VerificationEvidence]:
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
