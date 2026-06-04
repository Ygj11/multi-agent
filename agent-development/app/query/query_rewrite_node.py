from __future__ import annotations

"""Entity-aware query rewrite node."""

from typing import Any

from app.llm.base import LLMProvider
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.query.entity_extractor import EntityExtractor
from app.query.json_utils import parse_json_object
from app.schemas.entities import ConversationWindow, EntityBag, EntityMention
from app.schemas.query_rewrite import QueryRewriteResult


WEAK_FOLLOW_UP_SIGNALS = ("这个", "那个", "继续", "刚才", "上一轮", "前面", "它", "谁的问题")


class QueryRewriteNode:
    """Rewrite query using dynamic entities and conversation memory."""

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        entity_extractor: EntityExtractor | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.prompt_loader = prompt_loader or default_prompt_loader

    async def rewrite(
        self,
        original_query: str,
        recent_messages: list[dict[str, Any]] | None = None,
        short_summary: str | None = None,
        session_key: str = "",
    ) -> QueryRewriteResult:
        """Rewrite the query and return dynamic entities plus clarification state."""
        current_bag = self.entity_extractor.extract(original_query, source="current_query")
        history_bag = self.entity_extractor.extract_from_summary(short_summary)
        history_bag.merge(self.entity_extractor.extract_from_recent_turns(recent_messages or []))
        window_bag = EntityBag().merge(history_bag).merge(current_bag)
        window = ConversationWindow(
            session_key=session_key,
            summary=short_summary,
            recent_turns=recent_messages or [],
            entity_bag=window_bag,
        )

        llm_result = await self._rewrite_with_llm(original_query, current_bag, window)
        if llm_result is not None:
            return llm_result

        return self._rewrite_with_rules(original_query, current_bag, history_bag, window)

    async def _rewrite_with_llm(
        self,
        original_query: str,
        current_bag: EntityBag,
        window: ConversationWindow,
    ) -> QueryRewriteResult | None:
        if not self._should_use_llm_json():
            return None
        response = await self.llm_provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_loader.render("query_rewrite/system.md"),
                },
                {
                    "role": "user",
                    "content": self.prompt_loader.render(
                        "query_rewrite/user.md",
                        original_query=original_query,
                        current_entities=current_bag.to_compact_dict(),
                        conversation_window=window.model_dump(),
                    ),
                },
            ],
            tools=None,
            scene="query_rewrite",
        )
        data = parse_json_object(response.content)
        if data is None:
            return None
        resolved_query = str(data.get("resolved_query") or original_query)
        entities = self._merge_llm_entities(current_bag, data.get("entities"))
        inherited = self._compact_dict(data.get("inherited_entities"))
        merged_bag = EntityBag().merge(window.entity_bag).merge(EntityBag.from_compact_dict(entities, source="llm", confidence=0.85))
        return QueryRewriteResult(
            original_query=original_query,
            rewritten_query=resolved_query,
            is_follow_up=bool(data.get("is_follow_up", False)),
            resolved_query=resolved_query,
            rewrite_type=str(data.get("rewrite_type") or "direct"),
            entities=entities,
            inherited_entities=inherited,
            missing_required_entities=[str(item) for item in data.get("missing_required_entities") or []],
            need_clarification=bool(data.get("need_clarification", False)),
            clarification_question=data.get("clarification_question"),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            reason=str(data.get("reason") or "llm_json_rewrite"),
            entity_bag=merged_bag.model_dump(),
            conversation_window=window.model_dump(),
        )

    def _rewrite_with_rules(
        self,
        original_query: str,
        current_bag: EntityBag,
        history_bag: EntityBag,
        window: ConversationWindow,
    ) -> QueryRewriteResult:
        is_follow_up = self._is_follow_up(original_query, current_bag)
        inherited_bag = EntityBag()
        need_clarification = False
        clarification_question: str | None = None

        if is_follow_up and not current_bag.to_compact_dict():
            for entity_type, mentions in sorted(history_bag.entities.items()):
                values = history_bag.get_values(entity_type)
                if len(values) == 1 and history_bag.has_unique_high_confidence(entity_type):
                    best = history_bag.get_best(entity_type)
                    if best:
                        inherited_bag.add(
                            EntityMention(
                                type=entity_type,
                                value=best.value,
                                normalized_value=best.normalized_value,
                                confidence=best.confidence,
                                source=best.source,
                                turn_id=best.turn_id,
                                sensitive=best.sensitive,
                                metadata={**best.metadata, "inherited": True},
                            )
                        )
                elif len(values) > 1:
                    need_clarification = True
                    clarification_question = f"上下文里有多个 {entity_type}，请明确你要继续处理哪一个。"
                    break
            if not inherited_bag.to_compact_dict() and not need_clarification:
                need_clarification = True
                clarification_question = "请补充要处理的保单号、理赔号、请求流水号或错误码。"

        effective_bag = EntityBag().merge(current_bag).merge(inherited_bag)
        entities = effective_bag.to_compact_dict()
        rewritten_query = self._build_resolved_query(original_query, entities, is_follow_up)
        rewrite_type = "clarification_required" if need_clarification else "contextual_follow_up" if is_follow_up else "direct"

        return QueryRewriteResult(
            original_query=original_query,
            rewritten_query=rewritten_query,
            is_follow_up=is_follow_up,
            resolved_query=rewritten_query,
            rewrite_type=rewrite_type,
            entities=entities,
            inherited_entities=inherited_bag.to_compact_dict(),
            missing_required_entities=[],
            need_clarification=need_clarification,
            clarification_question=clarification_question,
            confidence=0.82 if not need_clarification else 0.4,
            reason="entity_bag_rule_rewrite",
            entity_bag=EntityBag().merge(window.entity_bag).merge(effective_bag).model_dump(),
            conversation_window=window.model_dump(),
        )

    @staticmethod
    def _is_follow_up(query: str, current_bag: EntityBag) -> bool:
        if current_bag.to_compact_dict():
            return False
        return any(signal in query for signal in WEAK_FOLLOW_UP_SIGNALS) or len(query.strip()) <= 16

    @staticmethod
    def _build_resolved_query(query: str, entities: dict[str, Any], is_follow_up: bool) -> str:
        request_id = entities.get("request_id")
        error_code = entities.get("error_code")
        if is_follow_up and request_id and error_code:
            return f"继续排查上一轮 requestId={request_id} 的 {error_code} 签名校验失败问题，并判断问题归属"
        if request_id and error_code:
            return f"排查 requestId={request_id} 的健康险个险接口 {error_code} 错误原因"
        if is_follow_up and error_code:
            return f"继续排查上一轮 requestId 的 {error_code} 签名校验失败问题，并判断问题归属"
        if is_follow_up and entities:
            inherited = "，".join(f"{key}={value}" for key, value in entities.items())
            return f"{query}（沿用上下文：{inherited}）"
        return query

    @staticmethod
    def _compact_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @classmethod
    def _merge_llm_entities(cls, current_bag: EntityBag, llm_entities: Any) -> dict[str, Any]:
        bag = EntityBag().merge(current_bag)
        if isinstance(llm_entities, dict):
            bag.merge(EntityBag.from_compact_dict(llm_entities, source="llm", confidence=0.85))
        return bag.to_compact_dict()

    def _should_use_llm_json(self) -> bool:
        if self.llm_provider is None:
            return False
        if self.llm_provider.__class__.__name__ == "InternalLLMProvider" and not getattr(self.llm_provider, "base_url", None):
            return False
        return True
