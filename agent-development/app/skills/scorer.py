from __future__ import annotations

"""Rule scoring for metadata-only skill selection."""

from dataclasses import dataclass
import re

from app.schemas.skill import SkillMetadata, SkillSelectionContext


@dataclass(frozen=True)
class ScoredSkill:
    """A skill candidate plus its deterministic rule score."""

    skill: SkillMetadata
    score: float
    reason: str


class SkillRuleScorer:
    """Scores skill metadata without reading any SKILL.md body content."""

    def score(self, context: SkillSelectionContext, skill: SkillMetadata) -> ScoredSkill:
        score = 0.0
        reasons: list[str] = []
        query_text = self._query_text(context)
        skill_text = self._skill_text(skill)

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

        domain_score, domain_reasons = self._domain_specific_score(context, skill, query_text)
        score += domain_score
        reasons.extend(domain_reasons)

        return ScoredSkill(skill=skill, score=score, reason="; ".join(reasons) or "no metadata keyword matched")

    @staticmethod
    def _query_text(context: SkillSelectionContext) -> str:
        return " ".join(
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

    @staticmethod
    def _skill_text(skill: SkillMetadata) -> str:
        return " ".join(
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
        lowered = text.lower()
        tokens = set(re.findall(r"[a-z0-9_]{2,}", lowered))
        for segment in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
            tokens.add(segment)
            if len(segment) > 8:
                for size in (2, 3, 4):
                    tokens.update(segment[index : index + size] for index in range(0, len(segment) - size + 1))
        stopwords = {"问题", "一下", "这个", "帮我", "看看", "处理", "troubleshooting"}
        return sorted(token for token in tokens if token not in stopwords)

    @staticmethod
    def _domain_specific_score(
        context: SkillSelectionContext,
        skill: SkillMetadata,
        query_text: str,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        skill_id = skill.skill_id

        if skill_id.endswith("signature_error") and (
            context.extracted_error_code
            or "e102" in query_text
            or "timestamp" in query_text
            or "签名" in query_text
        ):
            score += 4
            reasons.append("signature troubleshooting signal matched")

        if skill_id.endswith("missing_field") and any(
            token in query_text for token in ("appid", "field", "字段", "缺失", "不能为空")
        ):
            score += 4
            reasons.append("missing field signal matched")

        if skill_id.endswith("callback_failure") and any(
            token in query_text for token in ("callback", "回调", "鍥炶皟")
        ):
            score += 4
            reasons.append("callback failure signal matched")

        if skill_id.endswith("refund_failure") and any(token in query_text for token in ("退保", "退款", "refund")):
            score += 4
            reasons.append("refund signal matched")

        if skill_id.endswith("endo_completion_aftercare") and any(
            token in query_text
            for token in (
                "保全",
                "保全任务完成",
                "保单信息未更新",
                "保单未解锁",
                "未发起退费",
                "没有发短信",
                "apply_",
                "apply_seq",
            )
        ):
            score += 4
            reasons.append("endorsement aftercare signal matched")

        return score, reasons
