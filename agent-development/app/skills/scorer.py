from __future__ import annotations

"""Rule scoring for metadata-only skill selection."""

from dataclasses import dataclass
import re

from app.schemas.skill import SkillMetadata, SkillSelectionContext
from app.skills.scoring_policy import SkillScoringPolicy


@dataclass(frozen=True)
class ScoredSkill:
    """A skill candidate plus its deterministic rule score."""

    skill: SkillMetadata
    score: float
    reason: str


class SkillRuleScorer:
    """Scores skill metadata without reading any SKILL.md body content."""

    def __init__(self, policy: SkillScoringPolicy | None = None) -> None:
        self.policy = policy or SkillScoringPolicy.load()

    def score(self, context: SkillSelectionContext, skill: SkillMetadata) -> ScoredSkill:
        score = 0.0
        reasons: list[str] = []
        has_strong_signal = False
        query_text = self._query_text(context)
        skill_text = self._skill_text(skill)

        if context.intent and skill.intent and context.intent.lower() == skill.intent.lower():
            score += self.policy.weight("intent_tag_match")
            reasons.append(f"intent matched: {context.intent}")
        elif context.intent and any(context.intent.lower() == tag.lower() for tag in skill.intent_tags):
            score += self.policy.weight("intent_tag_match")
            reasons.append(f"intent tag matched: {context.intent}")

        if context.sub_intent and any(context.sub_intent.lower() == item.lower() for item in skill.sub_intents):
            score += self.policy.weight("sub_intent_tag_match")
            reasons.append(f"sub_intent matched: {context.sub_intent}")
            has_strong_signal = True
        elif context.sub_intent and any(context.sub_intent.lower() == tag.lower() for tag in skill.intent_tags):
            score += self.policy.weight("sub_intent_tag_match")
            reasons.append(f"sub_intent tag matched: {context.sub_intent}")
            has_strong_signal = True

        for tag in skill.intent_tags:
            tag_text = tag.lower()
            if tag_text and tag_text in query_text:
                score += self.policy.weight("intent_tag_keyword_match")
                reasons.append(f"intent tag keyword matched: {tag}")

        for token in self._tokens(context.original_query + " " + context.rewritten_query):
            if token and token in skill.description.lower():
                score += self.policy.weight("description_keyword_match")
                reasons.append(f"description keyword matched: {token}")

        for entity_type in skill.required_entities:
            if context.entities.get(entity_type):
                score += self.policy.weight("required_entity_present")
                reasons.append(f"required entity present: {entity_type}")
                has_strong_signal = True

        for entity_type in skill.optional_entities:
            if context.entities.get(entity_type):
                score += self.policy.weight("optional_entity_present")
                reasons.append(f"optional entity present: {entity_type}")

        for required in skill.required_context:
            if self._has_required_context(context, required):
                score += self.policy.weight("required_context_present")
                reasons.append(f"required context present: {required}")
                has_strong_signal = True

        if set(context.business_domain).intersection(skill.business_domain):
            score += self.policy.weight("business_domain_match")
            reasons.append("business domain matched")

        if context.extracted_interface_name and context.extracted_interface_name.lower() in skill_text:
            score += self.policy.weight("interface_match")
            reasons.append(f"interface matched: {context.extracted_interface_name}")
            has_strong_signal = True

        if context.extracted_error_code and context.extracted_error_code.lower() in skill_text:
            score += self.policy.weight("error_code_match")
            reasons.append(f"error code matched: {context.extracted_error_code}")
            has_strong_signal = True

        for keyword in skill.routing_keywords:
            if keyword and keyword.lower() in query_text:
                score += self.policy.weight("routing_keyword_match")
                reasons.append(f"routing keyword matched: {keyword}")
                has_strong_signal = True

        for keyword in skill.routing_negative_keywords:
            if keyword and keyword.lower() in query_text:
                score += self.policy.weight("routing_negative_keyword_match")
                reasons.append(f"routing negative keyword matched: {keyword}")

        if skill.required_entities and not has_strong_signal and score >= 7.0:
            score = 6.0
            reasons.append("capped below confidence threshold: no strong skill signal")

        return ScoredSkill(skill=skill, score=score, reason="; ".join(reasons) or "no metadata keyword matched")

    @staticmethod
    def _query_text(context: SkillSelectionContext) -> str:
        return " ".join(
            [
                context.original_query,
                context.rewritten_query,
                context.short_summary or "",
                context.recent_messages_summary or "",
                " ".join(context.lightweight_knowledge_hints),
                " ".join(str(value) for value in context.entities.values()),
                context.extracted_error_code or "",
                context.extracted_interface_name or "",
            ]
        ).lower()

    @staticmethod
    def _skill_text(skill: SkillMetadata) -> str:
        return " ".join(
            [
                skill.skill_id,
                skill.name,
                skill.description,
                skill.intent or "",
                " ".join(skill.sub_intents),
                " ".join(skill.intent_tags),
                " ".join(skill.required_entities),
                " ".join(skill.optional_entities),
                " ".join(skill.required_context),
                " ".join(skill.business_domain),
                " ".join(skill.routing_keywords),
                " ".join(skill.routing_negative_keywords),
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
