from __future__ import annotations

"""Context builder for orchestrator and sub-agent execution."""

from pathlib import Path
from typing import Any

from app.knowledge.service import KnowledgeService
from app.schemas.runtime import OrchestratorContext, SubAgentContext
from app.schemas.subagent import SubAgentTask
from app.runtime.context.knowledge_hint_builder import KnowledgeHintBuilder
from app.runtime.context.skill_context_resolver import SkillContextResolver
from app.skills.catalog import SkillCatalog
from app.skills.loader import SkillLoader
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
        self.skills_root = Path(skills_root)
        self.knowledge_service = knowledge_service
        self.skill_catalog = skill_catalog or SkillCatalog(self.skills_root)
        self.skill_loader = SkillLoader(self.skill_catalog)
        self.skill_selector = skill_selector or SkillSelector()
        self.knowledge_hint_builder = KnowledgeHintBuilder(knowledge_service=knowledge_service)
        self.skill_context_resolver = SkillContextResolver(
            skill_catalog=self.skill_catalog,
            skill_loader=self.skill_loader,
            skill_selector=self.skill_selector,
        )

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
        agent_candidate_summaries: list[dict[str, Any]] | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> OrchestratorContext:
        hints = await self.knowledge_hint_builder.build_lightweight_hints(
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
            agent_candidate_summaries=agent_candidate_summaries or [],
            lightweight_knowledge_hints=hints,
            auth_context=auth_context,
        )

    async def build_for_subagent(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        allowed_tools: list[str],
    ) -> SubAgentContext:
        agent_card_data = task.metadata.get("agent_card")
        resolution = await self.skill_context_resolver.resolve(task=task, parent_context=parent_context)
        selection = resolution.selection
        entity_check = resolution.entity_check

        namespaces = agent_card_data.get("rag_namespaces", []) if isinstance(agent_card_data, dict) else []
        knowledge_hint = await self.knowledge_hint_builder.build_subagent_knowledge_hint(
            query=parent_context.rewritten_query,
            namespaces=namespaces,
        )
        return SubAgentContext(
            task=task.model_dump(),
            rewritten_query=parent_context.rewritten_query,
            intent=parent_context.intent,
            allowed_tools=allowed_tools,
            skill_content=resolution.skill_content,
            selected_skill_id=selection.selected_skill_id,
            selected_skill_metadata=selection.selected_skill_metadata.model_dump() if selection.selected_skill_metadata else None,
            skill_selection_score=selection.score,
            skill_selection_reason=selection.reason,
            missing_required_entities=entity_check.missing_required_entities if entity_check else [],
            need_clarification=entity_check.need_clarification if entity_check else False,
            clarification_question=entity_check.clarification_question if entity_check else None,
            knowledge_hint=knowledge_hint,
            auth_context=parent_context.auth_context,
        )
