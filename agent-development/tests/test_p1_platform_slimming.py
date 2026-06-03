from __future__ import annotations

from pathlib import Path

from app.runtime.context.knowledge_hint_builder import KnowledgeHintBuilder
from app.runtime.context.skill_context_resolver import SkillContextResolver
from app.runtime.context_builder import ContextBuilder
from app.runtime.handlers.memory_commit_handler import MemoryCommitHandler
from app.runtime.handlers.message_commit_handler import MessageCommitHandler
from app.skills.reranker import SkillLLMReranker
from app.skills.scorer import SkillRuleScorer
from app.skills.selection_policy import SkillSelectionPolicy
from app.skills.selector import SkillSelector


def test_skill_selector_is_composed_from_scorer_reranker_and_policy():
    selector = SkillSelector()

    assert isinstance(selector.scorer, SkillRuleScorer)
    assert isinstance(selector.reranker, SkillLLMReranker)
    assert isinstance(selector.selection_policy, SkillSelectionPolicy)


def test_context_builder_uses_dedicated_skill_and_knowledge_helpers():
    builder = ContextBuilder(skills_root=Path("app/skills"))

    assert isinstance(builder.skill_context_resolver, SkillContextResolver)
    assert isinstance(builder.knowledge_hint_builder, KnowledgeHintBuilder)


def test_message_and_memory_commit_handlers_have_separate_responsibilities():
    assert hasattr(MessageCommitHandler, "save_user_message")
    assert hasattr(MessageCommitHandler, "save_assistant_message")
    assert not hasattr(MessageCommitHandler, "compress_short_memory")
    assert hasattr(MemoryCommitHandler, "compress_short_memory")
