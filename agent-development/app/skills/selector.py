from __future__ import annotations

"""规则版 SkillSelector。"""

from app.observability.logger import log_event, preview_text
from app.schemas.skill import SkillMetadata, SkillSelectionContext, SkillSelectionResult


class SkillSelector:
    """基于 metadata 和上下文做轻量规则匹配，不接 embedding 或真实 LLM。"""

    min_confident_score = 7.0

    async def select(
        self,
        *,
        agent_name: str,
        context: SkillSelectionContext,
        candidates: list[SkillMetadata],
    ) -> SkillSelectionResult:
        """从候选 skill metadata 中选择最合适的一项。"""
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
        if score < self.min_confident_score:
            selected = self._default_skill(candidates)
            score = 0.0
            reason = f"no confident match; fallback to default skill {selected.skill_id}"
            fallback = True
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
                "query_preview": preview_text(context.rewritten_query),
            },
        )
        return SkillSelectionResult(
            selected_skill_id=selected.skill_id,
            selected_skill_metadata=selected,
            score=score,
            reason=reason,
            fallback=fallback,
        )

    def _score(self, context: SkillSelectionContext, skill: SkillMetadata) -> tuple[float, str]:
        """计算候选 skill 与上下文的匹配分数。"""
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

    @staticmethod
    def _default_skill(candidates: list[SkillMetadata]) -> SkillMetadata:
        """选择 default skill；没有显式 default 时选择第一个 enabled skill。"""
        for candidate in candidates:
            if candidate.is_default:
                return candidate
        return candidates[0]

    @staticmethod
    def _has_required_context(context: SkillSelectionContext, required: str) -> bool:
        """判断 required_context 是否在上下文中存在。"""
        mapping = {
            "request_id": context.extracted_request_id,
            "error_code": context.extracted_error_code,
            "interface_name": context.extracted_interface_name,
            "short_summary": context.short_summary,
        }
        return bool(mapping.get(required))

    @staticmethod
    def _tokens(text: str) -> list[str]:
        """提取中英文关键词；中文短语通过原串匹配，英文按空白和符号拆分。"""
        separators = ",，。；;:：/\\|()[]{}<> \n\t"
        cleaned = text
        for sep in separators:
            cleaned = cleaned.replace(sep, " ")
        tokens = [item.strip().lower() for item in cleaned.split() if len(item.strip()) >= 2]
        chinese_keywords = [
            "签名",
            "签名校验失败",
            "字段缺失",
            "不能为空",
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
            "timestamp",
            "e102",
            "submitproposal",
        ]
        tokens.extend(keyword for keyword in chinese_keywords if keyword.lower() in text.lower())
        return sorted(set(tokens))
