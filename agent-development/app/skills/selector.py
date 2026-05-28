from __future__ import annotations

"""Hybrid SkillSelector based on metadata-only rule scoring and optional LLM rerank."""

from typing import Any

from app.llm.base import LLMProvider
from app.observability.logger import log_event, preview_text
from app.query.json_utils import parse_json_object
from app.schemas.skill import SkillMetadata, SkillSelectionContext, SkillSelectionResult


class SkillSelector:
    """Select one skill from metadata without reading skill bodies."""

    min_confident_score = 7.0
    min_llm_confidence = 0.45

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        enable_llm_rerank: bool = True,
        top_k: int = 3,
        min_margin: float = 3.0,
    ) -> None:
        self.llm_provider = llm_provider
        self.enable_llm_rerank = enable_llm_rerank
        self.top_k = top_k
        self.min_margin = min_margin

    async def select(
        self,
        *,
        agent_name: str,
        context: SkillSelectionContext,
        candidates: list[SkillMetadata],
    ) -> SkillSelectionResult:
        """Select the best skill from candidate metadata."""
        log_event(
            "skill_selection_started",
            request_id=context.request_id,
            trace_id=context.trace_id,
            session_key=context.session_key,
            node="skill_selector",
            message="Skill selection started",
            data={"agent_name": agent_name, "candidate_count": len(candidates)},
        )
        if not candidates:
            raise ValueError(f"no enabled skills for agent: {agent_name}")

        scored = [(candidate, *self._score(context, candidate)) for candidate in candidates]
        scored.sort(key=lambda item: item[1], reverse=True)
        selected, score, reason = scored[0]
        fallback = False
        selection_source = "rule"
        llm_confidence: float | None = None
        llm_reason: str | None = None

        if self._should_llm_rerank(context, scored):
            reranked = await self._llm_rerank(agent_name=agent_name, context=context, scored=scored[: self.top_k])
            if reranked is not None:
                selected, score, reason, llm_confidence, llm_reason = reranked
                selection_source = "llm_rerank"
            else:
                selection_source = "fallback"
                reason = f"llm rerank unavailable; fallback to rule top1: {reason}"

        if score < self.min_confident_score:
            selected = self._default_skill(candidates)
            score = 0.0
            reason = f"no confident match; fallback to default skill {selected.skill_id}"
            fallback = True
            selection_source = "fallback"
            log_event(
                "skill_selection_fallback",
                request_id=context.request_id,
                trace_id=context.trace_id,
                session_key=context.session_key,
                node="skill_selector",
                message="Skill selection fallback",
                data={"agent_name": agent_name, "selected_skill_id": selected.skill_id, "score": score, "reason": reason},
            )

        log_event(
            "skill_selected",
            request_id=context.request_id,
            trace_id=context.trace_id,
            session_key=context.session_key,
            node="skill_selector",
            message="Skill selected",
            data={
                "agent_name": agent_name,
                "selected_skill_id": selected.skill_id,
                "score": score,
                "reason": reason,
                "selection_source": selection_source,
                "llm_confidence": llm_confidence,
                "llm_reason": llm_reason,
                "query_preview": preview_text(context.rewritten_query),
            },
        )
        return SkillSelectionResult(
            selected_skill_id=selected.skill_id,
            selected_skill_metadata=selected,
            score=score,
            reason=reason,
            fallback=fallback,
            selection_source=selection_source,
            llm_confidence=llm_confidence,
            llm_reason=llm_reason,
        )

    def _score(self, context: SkillSelectionContext, skill: SkillMetadata) -> tuple[float, str]:
        """Score candidate skill metadata against the current context."""
        score = 0.0
        reasons: list[str] = []
        query_text = " ".join(
            [
                context.intent,
                context.original_query,
                context.rewritten_query,
                context.short_summary or "",
                context.recent_messages_summary or "",
                " ".join(context.lightweight_knowledge_hints),
                " ".join(str(value) for value in context.entities.values()),
                context.extracted_error_code or "",
                context.extracted_interface_name or "",
                context.sub_intent or "",
            ]
        ).lower()
        skill_text = " ".join(
            [
                skill.skill_id,
                skill.name,
                skill.description,
                " ".join(skill.intent_tags),
                " ".join(skill.required_entities),
                " ".join(skill.optional_entities),
                " ".join(skill.required_context),
                " ".join(skill.business_domain),
            ]
        ).lower()

        if context.intent and any(context.intent.lower() == tag.lower() for tag in skill.intent_tags):
            score += 3
            reasons.append(f"intent tag matched: {context.intent}")

        if context.sub_intent and any(context.sub_intent.lower() == tag.lower() for tag in skill.intent_tags):
            score += 3
            reasons.append(f"sub_intent tag matched: {context.sub_intent}")

        for tag in skill.intent_tags:
            tag_text = tag.lower()
            if tag_text and tag_text in query_text:
                score += 2
                reasons.append(f"intent tag keyword matched: {tag}")

        for token in self._tokens(context.original_query + " " + context.rewritten_query):
            if token and token in skill.description.lower():
                score += 1
                reasons.append(f"description keyword matched: {token}")

        for entity_type in skill.required_entities:
            if context.entities.get(entity_type):
                score += 2
                reasons.append(f"required entity present: {entity_type}")

        for entity_type in skill.optional_entities:
            if context.entities.get(entity_type):
                score += 1
                reasons.append(f"optional entity present: {entity_type}")

        for required in skill.required_context:
            if self._has_required_context(context, required):
                score += 1
                reasons.append(f"required context present: {required}")

        if set(context.business_domain).intersection(skill.business_domain):
            score += 1
            reasons.append("business domain matched")

        if context.extracted_interface_name and context.extracted_interface_name.lower() in skill_text:
            score += 2
            reasons.append(f"interface matched: {context.extracted_interface_name}")

        if context.extracted_error_code and context.extracted_error_code.lower() in skill_text:
            score += 3
            reasons.append(f"error code matched: {context.extracted_error_code}")

        return score, "; ".join(reasons) or "no metadata keyword matched"

    def _should_llm_rerank(self, context: SkillSelectionContext, scored: list[tuple[SkillMetadata, float, str]]) -> bool:
        if not self.enable_llm_rerank or self.llm_provider is None or len(scored) <= 1:
            return False
        top_score = scored[0][1]
        second_score = scored[1][1]
        query = f"{context.original_query} {context.rewritten_query}"
        semantic_signal = any(token in query for token in ("但是", "但", "却", "没有", "未", "完成", "结束", "成功", "after"))
        return (
            top_score < self.min_confident_score
            or top_score - second_score < self.min_margin
            or semantic_signal
            or len(query) >= 30
        )

    async def _llm_rerank(
        self,
        *,
        agent_name: str,
        context: SkillSelectionContext,
        scored: list[tuple[SkillMetadata, float, str]],
    ) -> tuple[SkillMetadata, float, str, float, str] | None:
        candidates = [candidate for candidate, _score, _reason in scored]
        candidate_ids = {candidate.skill_id for candidate in candidates}
        summaries = [self._metadata_summary(candidate, score, reason) for candidate, score, reason in scored]
        response = await self.llm_provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a metadata-only Skill router. Select exactly one skill_id from the provided "
                        "candidates. Do not invent skill_id. Return only JSON: selected_skill_id, confidence, reason."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Agent: {agent_name}\n"
                        f"Original query: {context.original_query}\n"
                        f"Rewritten query: {context.rewritten_query}\n"
                        f"Intent: {context.intent}\n"
                        f"Sub intent: {context.sub_intent}\n"
                        f"Entities: {context.entities}\n"
                        f"Candidates: {summaries}"
                    ),
                },
            ],
            tools=None,
            scene="skill_selection",
            request_id=context.request_id,
        )
        data = parse_json_object(response.content)
        if data is None:
            return None
        selected_skill_id = str(data.get("selected_skill_id") or "")
        if selected_skill_id not in candidate_ids:
            return None
        try:
            confidence = float(data.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            return None
        if confidence < self.min_llm_confidence:
            return None
        selected = next(candidate for candidate in candidates if candidate.skill_id == selected_skill_id)
        rule_score = next(score for candidate, score, _reason in scored if candidate.skill_id == selected_skill_id)
        llm_reason = str(data.get("reason") or "llm semantic rerank")
        reason = f"llm semantic rerank selected {selected_skill_id}; {llm_reason}"
        return selected, max(rule_score, self.min_confident_score), reason, confidence, llm_reason

    @staticmethod
    def _metadata_summary(skill: SkillMetadata, score: float, reason: str) -> dict[str, Any]:
        return {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "description": skill.description,
            "agent": skill.agent,
            "intent_tags": skill.intent_tags,
            "required_entities": skill.required_entities,
            "optional_entities": skill.optional_entities,
            "required_context": skill.required_context,
            "business_domain": skill.business_domain,
            "private_tools": skill.private_tools,
            "public_tools": skill.public_tools,
            "mcp_tools": skill.mcp_tools,
            "rule_score": score,
            "rule_reason": reason,
        }

    @staticmethod
    def _default_skill(candidates: list[SkillMetadata]) -> SkillMetadata:
        """Select the explicit default skill, otherwise the first enabled candidate."""
        for candidate in candidates:
            if candidate.is_default:
                return candidate
        return candidates[0]

    @staticmethod
    def _has_required_context(context: SkillSelectionContext, required: str) -> bool:
        mapping = {
            "request_id": context.extracted_request_id,
            "error_code": context.extracted_error_code,
            "interface_name": context.extracted_interface_name,
            "short_summary": context.short_summary,
            "apply_seq": context.entities.get("apply_seq"),
            "policy_no": context.entities.get("policy_no"),
            "endorseType": context.entities.get("endorseType"),
        }
        return bool(mapping.get(required))

    @staticmethod
    def _tokens(text: str) -> list[str]:
        separators = ",，。；;:：?？!！\\|()[]{}<> \n\t"
        cleaned = text
        for sep in separators:
            cleaned = cleaned.replace(sep, " ")
        tokens = [item.strip().lower() for item in cleaned.split() if len(item.strip()) >= 2]
        chinese_keywords = [
            "签名",
            "签名校验失败",
            "字段缺失",
            "不能为",
            "必填",
            "回调",
            "回调失败",
            "超时",
            "外发",
            "脱敏",
            "隐私",
            "错误码",
            "接口文档",
            "变更",
            "保全",
            "保全任务完成",
            "保单信息未更新",
            "保单未解锁",
            "未发起退费",
            "没有发短信",
            "财务创单",
            "收退费",
            "timestamp",
            "e102",
            "submitproposal",
        ]
        tokens.extend(keyword for keyword in chinese_keywords if keyword.lower() in text.lower())
        return sorted(set(tokens))
