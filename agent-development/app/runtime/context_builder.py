from __future__ import annotations

"""两级上下文构建器。"""

import re
from pathlib import Path
from typing import Any

from app.knowledge.service import KnowledgeService
from app.observability.logger import log_event
from app.schemas.runtime import OrchestratorContext, SubAgentContext
from app.schemas.entities import EntityBag
from app.schemas.skill import SkillSelectionContext
from app.schemas.subagent import SubAgentTask
from app.skills.catalog import SkillCatalog
from app.skills.loader import SkillLoader
from app.skills.required_entities import RequiredEntityChecker
from app.skills.selector import SkillSelector


class ContextBuilder:
    """独立公共组件，不属于主 Agent，也不属于子 Agent。"""

    def __init__(
        self,
        skills_root: Path,
        knowledge_service: KnowledgeService | None = None,
        skill_catalog: SkillCatalog | None = None,
        skill_selector: SkillSelector | None = None,
    ) -> None:
        """保存 skills 根目录和可选 KnowledgeService。"""
        self.skills_root = skills_root
        self.knowledge_service = knowledge_service
        self.skill_catalog = skill_catalog or SkillCatalog(skills_root)
        self.skill_loader = SkillLoader(self.skill_catalog)
        self.skill_selector = skill_selector or SkillSelector()
        self.required_entity_checker = RequiredEntityChecker()

    async def build_for_orchestrator(
        self,
        *,
        original_query: str,
        rewritten_query: str,
        intent: str,
        sub_intent: str | None = None,
        entities: dict[str, Any] | None = None,
        entity_bag: dict[str, Any] | None = None,
        conversation_window: dict[str, Any] | None = None,
        session_key: str,
        recent_messages: list[dict[str, Any]],
        short_summary: str | None,
        available_subagents: list[str],
        available_tools: list[str],
        agent_candidate_summaries: list[dict[str, Any]] | None = None,
    ) -> OrchestratorContext:
        """构建主 Agent 协调用轻量上下文。"""
        hints = await self._build_lightweight_hints(
            query=f"{original_query} {rewritten_query}",
            intent=intent,
        )
        compact_recent_messages = recent_messages[-10:]
        return OrchestratorContext(
            original_query=original_query,
            rewritten_query=rewritten_query,
            intent=intent,
            sub_intent=sub_intent,
            entities=entities or {},
            entity_bag=entity_bag or {},
            conversation_window=conversation_window or {},
            session_key=session_key,
            recent_messages=compact_recent_messages,
            short_summary=short_summary,
            available_subagents=available_subagents,
            available_tools=available_tools,
            agent_candidate_summaries=agent_candidate_summaries or [],
            lightweight_knowledge_hints=hints,
        )

    async def build_for_subagent(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        allowed_tools: list[str],
    ) -> SubAgentContext:
        """构建子 Agent 深度执行所需的任务级上下文。"""
        selection_context = self.build_skill_selection_context(task=task, parent_context=parent_context)
        agent_card_data = task.metadata.get("agent_card")
        allowed_skill_ids = set(agent_card_data.get("skills", [])) if isinstance(agent_card_data, dict) else set()
        candidates = self.skill_catalog.list_skills(task.name)
        if allowed_skill_ids:
            candidates = [candidate for candidate in candidates if candidate.skill_id in allowed_skill_ids]
        log_event(
            "skill_candidates_built",
            request_id=task.metadata.get("request_id"),
            trace_id=task.metadata.get("trace_id"),
            session_key=task.session_key,
            node="context_builder",
            message="Skill candidates built for subagent",
            data={"agent_name": task.name, "candidate_count": len(candidates), "skill_ids": [item.skill_id for item in candidates]},
        )
        if candidates:
            selection = await self.skill_selector.select(
                agent_name=task.name,
                context=selection_context,
                candidates=candidates,
            )
            task.metadata["skill_selection_score"] = selection.score
            task.metadata["skill_selection_reason"] = selection.reason
            task.metadata["skill_selection_fallback"] = selection.fallback
            if selection.fallback:
                skill_content = (
                    "No specific Skill matched confidently. Use the AgentCard, user query, "
                    "conversation context, and visible tools to reason and answer."
                )
                entity_check = None
                task.metadata["selected_skill_id"] = None
                task.metadata["selected_skill_metadata"] = None
                task.metadata["missing_required_entities"] = []
                task.metadata["need_clarification"] = False
                task.metadata["clarification_question"] = None
                log_event(
                    "skill_fallback_generic_execution",
                    request_id=task.metadata.get("request_id"),
                    trace_id=task.metadata.get("trace_id"),
                    session_key=task.session_key,
                    node="context_builder",
                    message="No confident skill match; continue with generic subagent execution",
                    data={"agent_name": task.name, "fallback_skill_id": selection.selected_skill_id, "reason": selection.reason},
                )
            else:
                loaded_skill = self.skill_loader.load(selection.selected_skill_id)
                entity_bag = EntityBag(**parent_context.entity_bag) if parent_context.entity_bag else EntityBag()
                entity_bag.merge(EntityBag.from_compact_dict(task.entities, source="rule", confidence=0.9))
                entity_check = self.required_entity_checker.check(
                    skill=selection.selected_skill_metadata,
                    entities=task.entities,
                    entity_bag=entity_bag,
                )
                task.entities = entity_check.entities
                skill_content = loaded_skill.content
                task.metadata["selected_skill_id"] = selection.selected_skill_id
                task.metadata["selected_skill_metadata"] = selection.selected_skill_metadata.model_dump()
                task.metadata["missing_required_entities"] = entity_check.missing_required_entities
                task.metadata["need_clarification"] = entity_check.need_clarification
                task.metadata["clarification_question"] = entity_check.clarification_question
            task.metadata["skill_selection_score"] = selection.score
            task.metadata["skill_selection_reason"] = selection.reason
            log_event(
                "skill_content_loaded",
                request_id=task.metadata.get("request_id"),
                trace_id=task.metadata.get("trace_id"),
                session_key=task.session_key,
                node="context_builder",
                message="Selected skill content loaded",
                data={
                    "agent_name": task.name,
                    "selected_skill_id": selection.selected_skill_id,
                    "score": selection.score,
                    "reason": selection.reason,
                },
            )
        else:
            # 兼容旧目录，避免迁移中断；新子 Agent skill 应全部来自 SkillCatalog。
            skill_content = self._read_skill(self._skill_name_for_task(task.name))
            selection = None
            entity_check = None
        mock_knowledge_hint = await self._build_subagent_knowledge_hint(parent_context.rewritten_query)
        troubleshooting_context = [
            message
            for message in parent_context.recent_messages
            if "E102" in str(message.get("content", "")) or "REQ_" in str(message.get("content", ""))
        ]
        return SubAgentContext(
            task=task.model_dump(),
            rewritten_query=parent_context.rewritten_query,
            intent=parent_context.intent,
            allowed_tools=allowed_tools,
            skill_content=skill_content,
            selected_skill_id=selection.selected_skill_id if selection and not selection.fallback else None,
            selected_skill_metadata=selection.selected_skill_metadata.model_dump() if selection and not selection.fallback else None,
            skill_selection_score=selection.score if selection else None,
            skill_selection_reason=selection.reason if selection else None,
            missing_required_entities=entity_check.missing_required_entities if entity_check else [],
            need_clarification=entity_check.need_clarification if entity_check else False,
            clarification_question=entity_check.clarification_question if entity_check else None,
            mock_knowledge_hint=mock_knowledge_hint,
            recent_troubleshooting_context=troubleshooting_context,
        )

    def build_skill_selection_context(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
    ) -> SkillSelectionContext:
        """为 SkillSelector 构建最小必要上下文。"""
        recent_summary = " ".join(str(item.get("content", "")) for item in parent_context.recent_messages[-6:])
        query = f"{task.original_query} {task.query} {parent_context.rewritten_query}"
        context = SkillSelectionContext(
            agent_name=task.name,
            intent=task.intent,
            sub_intent=parent_context.sub_intent,
            original_query=task.original_query,
            rewritten_query=parent_context.rewritten_query,
            session_key=task.session_key,
            entities=task.entities,
            entity_bag=parent_context.entity_bag,
            short_summary=parent_context.short_summary,
            recent_messages_summary=recent_summary[:1000],
            lightweight_knowledge_hints=parent_context.lightweight_knowledge_hints,
            request_id=task.metadata.get("request_id"),
            trace_id=task.metadata.get("trace_id"),
            extracted_error_code=self._extract_error_code(query),
            extracted_request_id=self._extract_request_id(query),
            extracted_interface_name=self._extract_interface_name(query),
        )
        return context

    @staticmethod
    def _skill_name_for_task(task_name: str) -> str:
        """将固定 Agent Catalog 名称映射到对应 skill 目录。"""
        mapping = {
            "troubleshooting_agent": "troubleshooting",
            "compliance_security_agent": "compliance_security",
            "document_parse_agent": "document_parse",
            "change_impact_analysis_agent": "change_impact_analysis",
        }
        return mapping.get(task_name, "troubleshooting")

    def _read_skill(self, name: str) -> str:
        """读取指定子 Agent 的 SKILL.md。"""
        skill_path = self.skills_root / name / "SKILL.md"
        return skill_path.read_text(encoding="utf-8")

    @staticmethod
    def _extract_error_code(text: str) -> str | None:
        """提取 E102 这类错误码。"""
        match = re.search(r"\bE\d{3,}\b", text)
        return match.group(0) if match else None

    @staticmethod
    def _extract_request_id(text: str) -> str | None:
        """提取 REQ_001 这类 requestId。"""
        match = re.search(r"\bREQ_\d+\b", text)
        return match.group(0) if match else None

    @staticmethod
    def _extract_interface_name(text: str) -> str | None:
        """提取当前 MVP 中常见接口名。"""
        if "submitProposal" in text:
            return "submitProposal"
        return None

    async def _build_lightweight_hints(self, query: str, intent: str) -> list[str]:
        """通过 KnowledgeService 获取主干轻量知识提示。"""
        if self.knowledge_service is None:
            return []
        chunks = await self.knowledge_service.pre_search(query=query, intent=intent, top_k=3)
        log_event(
            "knowledge_hint_loaded",
            node="context_builder",
            message="Lightweight knowledge hints loaded",
            data={"knowledge_hint_count": len(chunks), "sources": [chunk.source for chunk in chunks]},
        )
        return [chunk.content for chunk in chunks]

    async def _build_subagent_knowledge_hint(self, query: str) -> str | None:
        """通过 KnowledgeService 获取子 Agent 任务级知识提示。"""
        if self.knowledge_service is None:
            return None
        chunks = await self.knowledge_service.search(query=query, top_k=3)
        log_event(
            "subagent_context_built",
            node="context_builder",
            message="Subagent knowledge context built",
            data={"knowledge_hint_count": len(chunks), "sources": [chunk.source for chunk in chunks]},
        )
        if not chunks:
            return None
        return "\n".join(chunk.content for chunk in chunks)
