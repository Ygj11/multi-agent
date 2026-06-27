from __future__ import annotations

"""子 Agent 执行前的 Skill 上下文解析。"""

from dataclasses import dataclass

from app.observability.logger import log_event
from app.runtime.failure_codes import NO_CONFIDENT_SKILL, NO_ENABLED_SKILLS, NO_SKILL_POLICY_BLOCKED
from app.schemas.agent_card import AgentCard
from app.schemas.entities import EntityBag
from app.schemas.runtime import OrchestratorContext
from app.schemas.skill import SkillSelectionContext, SkillSelectionResult
from app.schemas.subagent import SubAgentTask
from app.skills.catalog import SkillCatalog
from app.skills.loader import SkillLoader
from app.skills.required_entities import RequiredEntityChecker, RequiredEntityCheckResult
from app.skills.selector import SkillSelector


@dataclass
class SkillResolution:
    """一次子 Agent 任务解析出的 Skill、内容与实体检查结果。"""

    selection: SkillSelectionResult
    skill_content: str
    entity_check: RequiredEntityCheckResult | None


class SkillContextResolver:
    """选择 Skill metadata，加载唯一选中的 Skill 正文，并检查必填实体。

    本类不重新选择 Agent，也不维护私有实体正则。实体从父级 resolved
    EntityBag/compact entities 读取，缺失或歧义时返回澄清。
    """

    generic_skill_content = (
        "No specific Skill matched confidently. Use the AgentCard, user query, "
        "conversation context, and visible tools to reason and answer."
    )

    def __init__(
        self,
        *,
        skill_catalog: SkillCatalog,
        skill_loader: SkillLoader,
        skill_selector: SkillSelector,
        required_entity_checker: RequiredEntityChecker | None = None,
        no_skill_policy: str = "clarify",
        app_env: str = "local",
    ) -> None:
        if no_skill_policy == "generic_dev_only" and app_env != "local":
            raise ValueError("NO_SKILL_POLICY=generic_dev_only is only allowed when APP_ENV=local")
        self.skill_catalog = skill_catalog
        self.skill_loader = skill_loader
        self.skill_selector = skill_selector
        self.required_entity_checker = required_entity_checker or RequiredEntityChecker()
        self.no_skill_policy = no_skill_policy
        self.app_env = app_env

    async def resolve(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        agent_card: AgentCard,
    ) -> SkillResolution:
        if task.execution_mode == "repair" and task.pinned_skill_id:
            return self._resolve_pinned_skill(task=task, parent_context=parent_context, agent_card=agent_card)

        selection_context = self.build_selection_context(task=task, parent_context=parent_context)
        candidates = self.build_candidates(task=task, agent_card=agent_card)

        # 先只用 metadata 选择 Skill，避免把所有 SKILL.md 内容塞进 LLM 上下文。
        selection = await self.skill_selector.select(
            agent_name=task.agent_name,
            context=selection_context,
            candidates=candidates,
        )

        self.write_selection_metadata(task, selection)

        if selection.selected_skill_id is None or selection.selected_skill_metadata is None:
            return self._resolve_no_skill(task=task, selection=selection)

        return self._resolve_selected_skill(task=task, parent_context=parent_context, selection=selection)

    def _resolve_pinned_skill(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        agent_card: AgentCard,
    ) -> SkillResolution:
        """Repair 模式固定第一次选中的 Skill，不再重新自由选择。"""
        metadata = self.skill_catalog.get_skill_metadata(str(task.pinned_skill_id))
        if metadata is None:
            raise ValueError(f"pinned skill not found: {task.pinned_skill_id}")
        if metadata.agent != task.agent_name:
            raise ValueError(f"pinned skill agent mismatch: {task.pinned_skill_id}")
        if metadata.skill_id not in set(agent_card.skills):
            raise ValueError(f"pinned skill is not declared by AgentCard: {metadata.skill_id}")
        if not metadata.enabled:
            raise ValueError(f"pinned skill is disabled: {metadata.skill_id}")

        selection = SkillSelectionResult(
            selected_skill_id=metadata.skill_id,
            selected_skill_metadata=metadata,
            score=100.0,
            reason="repair pinned skill",
            fallback=False,
            selection_source="pinned_repair",
            decision_trace={"skill_pin": "repair", "selected_skill_id": metadata.skill_id},
        )
        self.write_selection_metadata(task, selection)
        return self._resolve_selected_skill(task=task, parent_context=parent_context, selection=selection)

    def _resolve_selected_skill(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        selection: SkillSelectionResult,
    ) -> SkillResolution:
        # 只有选中 Skill 后才加载完整内容；随后基于 resolved EntityBag 检查必填实体。
        loaded_skill = self.skill_loader.load(selection.selected_skill_id)

        entity_bag = EntityBag(**parent_context.entity_bag) if parent_context.entity_bag else EntityBag.from_compact_dict(
            parent_context.entities or task.entities,
            source="rule",
            confidence=0.9,
        )
        resolved_entities = entity_bag.to_compact_dict()

        """Check required entities and determine if clarification is needed."""
        entity_check = self.required_entity_checker.check(
            skill=selection.selected_skill_metadata,
            entities=resolved_entities,
            entity_bag=entity_bag,
        )
        task.entities = entity_check.entities
        task.metadata["selected_skill_id"] = selection.selected_skill_id
        task.metadata["selected_skill_metadata"] = selection.selected_skill_metadata.model_dump()
        task.metadata["missing_required_entities"] = entity_check.missing_required_entities
        task.metadata["need_clarification"] = entity_check.need_clarification
        task.metadata["clarification_question"] = entity_check.clarification_question
        log_event(
            "skill_content_loaded",
            request_id=task.request_id,
            trace_id=task.trace_id,
            session_key=task.session_key,
            node="context_builder",
            message="Selected skill content loaded",
            data={
                "agent_name": task.agent_name,
                "selected_skill_id": selection.selected_skill_id,
                "score": selection.score,
                "reason": selection.reason,
            },
        )
        return SkillResolution(selection=selection, skill_content=loaded_skill.content, entity_check=entity_check)

    def _resolve_no_skill(self, *, task: SubAgentTask, selection: SkillSelectionResult) -> SkillResolution:
        # 默认 no-skill 策略是澄清/阻断，不进入泛化 LLM 执行。
        # generic_dev_only 只允许 local 环境显式打开，用于本地调试未配置 Skill 的场景。
        reason = selection.fallback_reason or (NO_ENABLED_SKILLS if selection.selection_source == "none" else NO_CONFIDENT_SKILL)
        task.metadata["selected_skill_id"] = None
        task.metadata["selected_skill_metadata"] = None
        task.metadata["missing_required_entities"] = []
        task.metadata["no_skill_policy"] = self.no_skill_policy
        task.metadata["no_skill_blocked"] = self.no_skill_policy != "generic_dev_only"
        task.metadata["skill_selection_fallback_reason"] = reason
        task.metadata["skill_selection_llm_status"] = selection.llm_status
        task.metadata["skill_selection_decision_trace"] = selection.decision_trace

        if self.no_skill_policy == "generic_dev_only":
            task.metadata["need_clarification"] = False
            task.metadata["clarification_question"] = None
            log_event(
                "skill_generic_dev_execution",
                request_id=task.request_id,
                trace_id=task.trace_id,
                session_key=task.session_key,
                node="context_builder",
                message="No confident skill match; generic execution allowed for local development",
                data={"agent_name": task.agent_name, "reason": selection.reason, "no_skill_policy": self.no_skill_policy},
            )
            return SkillResolution(selection=selection, skill_content=self.generic_skill_content, entity_check=None)

        if self.no_skill_policy == "answer_no_skill":
            question = "当前 Agent 没有匹配到可执行的业务技能，暂不继续调用工具。请补充更明确的业务场景或联系管理员配置对应 Skill。"
            need_clarification = False
        else:
            question = "当前问题没有匹配到可执行的业务技能，请补充更明确的业务场景、业务类型或关键编号后我再继续处理。"
            need_clarification = True

        task.metadata["need_clarification"] = need_clarification
        task.metadata["clarification_question"] = question
        log_event(
            "skill_no_match_blocked",
            request_id=task.request_id,
            trace_id=task.trace_id,
            session_key=task.session_key,
            node="context_builder",
            message="No confident skill match; blocked by no-skill policy",
            data={
                "agent_name": task.agent_name,
                "reason": selection.reason,
                "no_skill_policy": self.no_skill_policy,
                "fallback_reason": reason or NO_SKILL_POLICY_BLOCKED,
            },
        )
        return SkillResolution(selection=selection, skill_content="", entity_check=None)

    def build_candidates(self, *, task: SubAgentTask, agent_card: AgentCard):
        # Skill 候选必须同时属于当前 Agent，并且出现在 AgentCard.skills 白名单中。
        allowed_skill_ids = set(agent_card.skills)
        candidates = self.skill_catalog.list_skills(task.agent_name)
        candidates = [candidate for candidate in candidates if candidate.skill_id in allowed_skill_ids]
        log_event(
            "skill_candidates_built",
            request_id=task.request_id,
            trace_id=task.trace_id,
            session_key=task.session_key,
            node="context_builder",
            message="Skill candidates built for subagent",
            data={
                "agent_name": task.agent_name,
                "candidate_count": len(candidates),
                "skill_ids": [item.skill_id for item in candidates],
            },
        )
        return candidates

    def build_selection_context(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
    ) -> SkillSelectionContext:
        recent_summary = " ".join(str(item.get("content", "")) for item in parent_context.recent_messages[-6:])
        entity_bag = EntityBag(**parent_context.entity_bag) if parent_context.entity_bag else EntityBag.from_compact_dict(
            parent_context.entities or task.entities,
            source="rule",
            confidence=0.9,
        )
        # SkillSelectionContext 使用 compact entities 做打分，同时保留 entity_bag 供后续校验。
        entities = entity_bag.to_compact_dict()
        return SkillSelectionContext(
            agent_name=task.agent_name,
            intent=task.intent,
            sub_intent=parent_context.sub_intent,
            original_query=task.original_query,
            rewritten_query=parent_context.rewritten_query,
            session_key=task.session_key,
            entities=entities,
            entity_bag=entity_bag.model_dump(),
            short_summary=parent_context.short_summary,
            recent_messages_summary=recent_summary[:2000],
            lightweight_knowledge_hints=parent_context.lightweight_knowledge_hints,
            request_id=task.request_id,
            trace_id=task.trace_id,
            extracted_error_code=self._entity_value(entities, "error_code"),
            extracted_request_id=self._entity_value(entities, "request_id"),
        )

    @staticmethod
    def write_selection_metadata(task: SubAgentTask, selection: SkillSelectionResult) -> None:
        task.metadata["skill_selection_score"] = selection.score
        task.metadata["skill_selection_reason"] = selection.reason
        task.metadata["skill_selection_fallback"] = selection.fallback
        task.metadata["skill_selection_source"] = selection.selection_source
        task.metadata["skill_selection_llm_confidence"] = selection.llm_confidence
        task.metadata["skill_selection_llm_reason"] = selection.llm_reason
        task.metadata["skill_selection_llm_status"] = selection.llm_status
        task.metadata["skill_selection_fallback_reason"] = selection.fallback_reason
        task.metadata["skill_selection_decision_trace"] = selection.decision_trace

    @staticmethod
    def _entity_value(entities: dict[str, object], entity_type: str) -> str | None:
        value = entities.get(entity_type)
        if value in (None, "", []):
            return None
        if isinstance(value, list):
            return str(value[0]) if value else None
        return str(value)
