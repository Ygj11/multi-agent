from __future__ import annotations

"""主 Agent 与子 Agent 的上下文构建器。"""

from pathlib import Path
from typing import Any

from app.knowledge.service import KnowledgeService
from app.schemas.agent_card import AgentCard
from app.schemas.entities import EntityBag
from app.schemas.runtime import OrchestratorContext, SubAgentContext
from app.schemas.subagent import SubAgentTask
from app.runtime.context.knowledge_hint_builder import KnowledgeHintBuilder
from app.runtime.context.skill_context_resolver import SkillContextResolver
from app.skills.catalog import SkillCatalog
from app.skills.loader import SkillLoader
from app.skills.selector import SkillSelector


class ContextBuilder:
    """集中构建结构化上下文，避免后续节点重复查库和重复解析。

    `build_for_orchestrator` 构建父级上下文；`build_for_subagent` 在 Agent 已选定
    后委托 SkillContextResolver 选择 Skill，并生成子 Agent 执行上下文。
    """

    def __init__(
        self,
        skills_root: Path,
        knowledge_service: KnowledgeService | None = None,
        skill_catalog: SkillCatalog | None = None,
        skill_selector: SkillSelector | None = None,
        no_skill_policy: str = "clarify",
        app_env: str = "local",
    ) -> None:
        self.skills_root = Path(skills_root)
        self.knowledge_service = knowledge_service
        self.skill_catalog = skill_catalog or SkillCatalog(self.skills_root)
        self.skill_loader = SkillLoader(self.skill_catalog)
        self.skill_selector = skill_selector or SkillSelector()
        self.no_skill_policy = no_skill_policy
        self.app_env = app_env
        self.knowledge_hint_builder = KnowledgeHintBuilder(knowledge_service=knowledge_service)
        self.skill_context_resolver = SkillContextResolver(
            skill_catalog=self.skill_catalog,
            skill_loader=self.skill_loader,
            skill_selector=self.skill_selector,
            no_skill_policy=no_skill_policy,
            app_env=app_env,
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
        session_key: str,
        recent_messages: list[dict[str, Any]],
        short_summary: str | None,
        auth_context: dict[str, Any] | None = None,
    ) -> OrchestratorContext:
        compact_entities = entities or {}
        if entity_bag:
            # entity_bag 是事实源；父上下文中的 compact entities 始终由它重新生成。
            compact_entities = EntityBag(**entity_bag).to_compact_dict()
        hints = await self.knowledge_hint_builder.build_lightweight_hints(
            query=f"{original_query} {rewritten_query}",
            intent=intent,
        )
        return OrchestratorContext(
            original_query=original_query,
            rewritten_query=rewritten_query,
            intent=intent,
            sub_intent=sub_intent,
            entities=compact_entities,
            entity_bag=entity_bag or {},
            session_key=session_key,
            recent_messages=recent_messages[-10:],
            short_summary=short_summary,
            lightweight_knowledge_hints=hints,
            auth_context=auth_context,
        )

    async def build_for_subagent(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        agent_card: AgentCard,
        allowed_tools: list[str],
    ) -> SubAgentContext:
        # 子 Agent 上下文建立在已选 Agent 之上：这里才进行 Skill 选择和 Skill 内容加载。
        # AgentSelection 阶段不会读取完整 SKILL.md。
        resolution = await self.skill_context_resolver.resolve(
            task=task,
            parent_context=parent_context,
            agent_card=agent_card,
        )
        selection = resolution.selection
        entity_check = resolution.entity_check

        knowledge_hint = await self.knowledge_hint_builder.build_subagent_knowledge_hint(
            query=parent_context.rewritten_query,
            namespaces=agent_card.rag_namespaces,
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
            skill_selection_fallback=selection.fallback,
            skill_selection_source=selection.selection_source,
            execution_mode=task.execution_mode,
            repair_plan=task.repair_plan,
            previous_answer=task.previous_answer,
            previous_evidence=task.previous_evidence,
            previous_tool_calls=task.previous_tool_calls,
            repair_round=task.repair_round,
            do_not_repeat=task.do_not_repeat,
            no_skill_policy=task.metadata.get("no_skill_policy"),
            no_skill_blocked=bool(task.metadata.get("no_skill_blocked")),
            missing_required_entities=entity_check.missing_required_entities if entity_check else [],
            need_clarification=bool(task.metadata.get("need_clarification")) if entity_check is None else entity_check.need_clarification,
            clarification_question=task.metadata.get("clarification_question") if entity_check is None else entity_check.clarification_question,
            knowledge_hint=knowledge_hint,
            auth_context=parent_context.auth_context,
        )
