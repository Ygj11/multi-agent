from __future__ import annotations

"""Context builder for orchestrator and sub-agent execution."""

import re
from pathlib import Path
from typing import Any

from app.knowledge.service import KnowledgeService
from app.observability.logger import log_event
from app.schemas.entities import EntityBag
from app.schemas.runtime import OrchestratorContext, SubAgentContext
from app.schemas.skill import SkillSelectionContext
from app.schemas.subagent import SubAgentTask
from app.skills.catalog import SkillCatalog
from app.skills.loader import SkillLoader
from app.skills.required_entities import RequiredEntityChecker
from app.skills.selector import SkillSelector


class ContextBuilder:
    """Shared context builder independent from both the main agent and sub agents."""

    def __init__(
        self,
        skills_root: Path,
        knowledge_service: KnowledgeService | None = None,
        skill_catalog: SkillCatalog | None = None,
        skill_selector: SkillSelector | None = None,
    ) -> None:
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
        hints = await self._build_lightweight_hints(
            query=f"{original_query} {rewritten_query}",
            intent=intent,
        )
        return OrchestratorContext(
            original_query=original_query,
            rewritten_query=rewritten_query,
            intent=intent,
            sub_intent=sub_intent,
            entities=entities or {},
            entity_bag=entity_bag or {},
            conversation_window=conversation_window or {},
            session_key=session_key,
            recent_messages=recent_messages[-10:],
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
            data={
                "agent_name": task.name,
                "candidate_count": len(candidates),
                "skill_ids": [item.skill_id for item in candidates],
            },
        )
        if not candidates:
            raise ValueError(f"no enabled skills configured for agent: {task.name}")

        selection = await self.skill_selector.select(
            agent_name=task.name,
            context=selection_context,
            candidates=candidates,
        )
        # Write the selection metadata to the task
        self._write_selection_metadata(task, selection)

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

        knowledge_hint = await self._build_subagent_knowledge_hint(parent_context.rewritten_query)
        return SubAgentContext(
            task=task.model_dump(),
            rewritten_query=parent_context.rewritten_query,
            intent=parent_context.intent,
            allowed_tools=allowed_tools,
            skill_content=skill_content,
            selected_skill_id=selection.selected_skill_id if not selection.fallback else None,
            selected_skill_metadata=selection.selected_skill_metadata.model_dump() if not selection.fallback else None,
            skill_selection_score=selection.score,
            skill_selection_reason=selection.reason,
            missing_required_entities=entity_check.missing_required_entities if entity_check else [],
            need_clarification=entity_check.need_clarification if entity_check else False,
            clarification_question=entity_check.clarification_question if entity_check else None,
            knowledge_hint=knowledge_hint,
        )

    def build_skill_selection_context(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
    ) -> SkillSelectionContext:
        recent_summary = " ".join(str(item.get("content", "")) for item in parent_context.recent_messages[-6:])
        query = f"{task.original_query} {task.query} {parent_context.rewritten_query}"
        return SkillSelectionContext(
            agent_name=task.name,
            intent=task.intent,
            sub_intent=parent_context.sub_intent,
            original_query=task.original_query,
            rewritten_query=parent_context.rewritten_query,
            session_key=task.session_key,
            entities=task.entities,
            entity_bag=parent_context.entity_bag,
            short_summary=parent_context.short_summary,
            recent_messages_summary=recent_summary[:2000],
            lightweight_knowledge_hints=parent_context.lightweight_knowledge_hints,
            request_id=task.metadata.get("request_id"),
            trace_id=task.metadata.get("trace_id"),
            extracted_error_code=self._extract_error_code(query),
            extracted_request_id=self._extract_request_id(query),
            extracted_interface_name=self._extract_interface_name(query),
        )

    @staticmethod
    def _write_selection_metadata(task: SubAgentTask, selection) -> None:
        task.metadata["skill_selection_score"] = selection.score
        task.metadata["skill_selection_reason"] = selection.reason
        task.metadata["skill_selection_fallback"] = selection.fallback
        task.metadata["skill_selection_source"] = selection.selection_source
        task.metadata["skill_selection_llm_confidence"] = selection.llm_confidence
        task.metadata["skill_selection_llm_reason"] = selection.llm_reason

    @staticmethod
    def _extract_error_code(text: str) -> str | None:
        match = re.search(r"\bE\d{3,}\b", text)
        return match.group(0) if match else None

    @staticmethod
    def _extract_request_id(text: str) -> str | None:
        match = re.search(r"\bREQ_\d+\b", text)
        return match.group(0) if match else None

    @staticmethod
    def _extract_interface_name(text: str) -> str | None:
        if "submitProposal" in text:
            return "submitProposal"
        return None

    async def _build_lightweight_hints(self, query: str, intent: str) -> list[str]:
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
