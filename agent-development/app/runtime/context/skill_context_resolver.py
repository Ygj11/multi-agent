from __future__ import annotations

"""Skill context resolution for sub-agent execution."""

from dataclasses import dataclass
import re

from app.observability.logger import log_event
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
    """Resolved skill context details for one sub-agent task."""

    selection: SkillSelectionResult
    skill_content: str
    entity_check: RequiredEntityCheckResult | None


class SkillContextResolver:
    """Selects skill metadata, loads only the selected body, and checks entities."""

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
    ) -> None:
        self.skill_catalog = skill_catalog
        self.skill_loader = skill_loader
        self.skill_selector = skill_selector
        self.required_entity_checker = required_entity_checker or RequiredEntityChecker()

    async def resolve(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
    ) -> SkillResolution:
        selection_context = self.build_selection_context(task=task, parent_context=parent_context)
        """获得候选的 skills"""
        candidates = self.build_candidates(task=task)

        """Select the best skill from candidates using metadata only, without loading skill bodies."""
        selection = await self.skill_selector.select(
            agent_name=task.name,
            context=selection_context,
            candidates=candidates,
        )

        self.write_selection_metadata(task, selection)


        """When no skill matches, continue with generic sub-agent context."""
        if selection.selected_skill_id is None or selection.selected_skill_metadata is None:
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
                data={"agent_name": task.name, "reason": selection.reason},
            )
            return SkillResolution(selection=selection, skill_content=self.generic_skill_content, entity_check=None)

        """Load the selected skill content and check required entities."""
        loaded_skill = self.skill_loader.load(selection.selected_skill_id)

        entity_bag = EntityBag(**parent_context.entity_bag) if parent_context.entity_bag else EntityBag()
        entity_bag.merge(EntityBag.from_compact_dict(task.entities, source="rule", confidence=0.9))

        """Check required entities and determine if clarification is needed."""
        entity_check = self.required_entity_checker.check(
            skill=selection.selected_skill_metadata,
            entities=task.entities,
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
        return SkillResolution(selection=selection, skill_content=loaded_skill.content, entity_check=entity_check)

    def build_candidates(self, *, task: SubAgentTask):
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
        return candidates

    def build_selection_context(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
    ) -> SkillSelectionContext:
        recent_summary = " ".join(str(item.get("content", "")) for item in parent_context.recent_messages[-6:])
        query = f"{task.original_query} {task.query} {parent_context.rewritten_query}"
        merged_entities = {**parent_context.entities, **task.entities}
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
            extracted_error_code=self._entity_value(merged_entities, "error_code") or self.extract_error_code(query),
            extracted_request_id=self._entity_value(merged_entities, "request_id") or self.extract_request_id(query),
            extracted_interface_name=self._entity_value(merged_entities, "interface_name") or self.extract_interface_name(query),
        )

    @staticmethod
    def write_selection_metadata(task: SubAgentTask, selection: SkillSelectionResult) -> None:
        task.metadata["skill_selection_score"] = selection.score
        task.metadata["skill_selection_reason"] = selection.reason
        task.metadata["skill_selection_fallback"] = selection.fallback
        task.metadata["skill_selection_source"] = selection.selection_source
        task.metadata["skill_selection_llm_confidence"] = selection.llm_confidence
        task.metadata["skill_selection_llm_reason"] = selection.llm_reason

    @staticmethod
    def extract_error_code(text: str) -> str | None:
        match = re.search(r"\bE\d{3,}\b", text)
        return match.group(0) if match else None

    @staticmethod
    def extract_request_id(text: str) -> str | None:
        match = re.search(r"\bREQ_\d+\b", text)
        return match.group(0) if match else None

    @staticmethod
    def extract_interface_name(text: str) -> str | None:
        if "submitProposal" in text:
            return "submitProposal"
        return None

    @staticmethod
    def _entity_value(entities: dict[str, object], entity_type: str) -> str | None:
        value = entities.get(entity_type)
        if value in (None, "", []):
            return None
        if isinstance(value, list):
            return str(value[0]) if value else None
        return str(value)
