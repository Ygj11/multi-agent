from pathlib import Path

import pytest

from app.agents.card_loader import AgentCardLoader
from app.query.intent_taxonomy_loader import IntentTaxonomyLoader
from app.schemas.agent_card import AgentAccessPolicy
from app.schemas.intent_taxonomy import IntentDefinition, IntentTaxonomy, SubIntentDefinition
from app.skills.catalog import SkillCatalog


CARDS_ROOT = Path("app/agents/cards")
SKILLS_ROOT = Path("app/skills")


def _taxonomy_with_routes(routes: dict[str, list[str]]) -> IntentTaxonomy:
    return IntentTaxonomy(
        intents={
            intent: IntentDefinition(
                display_name=intent,
                description=f"{intent} description",
                sub_intents={
                    sub_intent: SubIntentDefinition(
                        display_name=sub_intent,
                        description=f"{sub_intent} description",
                    )
                    for sub_intent in sub_intents
                },
            )
            for intent, sub_intents in routes.items()
        }
    )


def _write_minimal_card(
    cards_root: Path,
    *,
    filename: str = "agent.yaml",
    agent_name: str = "test_agent",
    supported_routes: str = "troubleshooting:\n    - signature_error",
    enabled: bool = True,
) -> None:
    cards_root.mkdir(exist_ok=True)
    (cards_root / filename).write_text(
        f"""
agent_name: {agent_name}
display_name: Test
description: Test agent
capabilities:
  - test_capability
supported_routes:
  {supported_routes}
required_entities: []
optional_entities: []
output_schema: SubAgentResult
private_tools: []
public_tools_allowed: true
skills: []
rag_namespaces: []
memory_policy: {{"use_short_summary": true, "recent_turns": 1}}
examples: []
enabled: {str(enabled).lower()}
version: "1.0.0"
""",
        encoding="utf-8",
    )


def test_agent_card_yaml_loads_required_fields():
    loader = AgentCardLoader(CARDS_ROOT)
    cards = {card.agent_name: card for card in loader.load_all(force_reload=True)}

    assert "troubleshooting_agent" in cards
    card = cards["troubleshooting_agent"]
    assert card.display_name
    assert "query_internal_log" in card.private_tools
    assert card.public_tools_allowed is True
    assert card.supported_intents == ["troubleshooting"]
    assert "endo_completion_aftercare" in card.supported_sub_intents
    assert card.normalized_supported_routes()["troubleshooting"] == [
        "callback_failure",
        "endo_completion_aftercare",
        "missing_field",
        "refund_failure",
        "signature_error",
    ]
    assert "troubleshooting_agent.signature_error" in card.skills
    assert "troubleshooting" in card.rag_namespaces


def test_troubleshooting_agent_declares_endo_aftercare_skill_and_tools():
    card = AgentCardLoader(CARDS_ROOT).get_agent_card("troubleshooting_agent")

    assert "troubleshooting_agent.endo_completion_aftercare" in card.skills
    for tool_name in {
        "query_endo_task_record",
        "notice_policy_update",
        "notice_customer_update",
        "notice_period_update",
        "policy_suspendOrRecovery",
        "notice_finance",
    }:
        assert tool_name in card.private_tools


def test_agent_card_missing_required_field_fails(tmp_path):
    cards_root = tmp_path / "cards"
    cards_root.mkdir()
    (cards_root / "broken.yaml").write_text(
        """
agent_name: broken_agent
display_name: Broken
description: Missing output schema
capabilities:
  - broken
supported_intents:
  - broken
version: "1.0.0"
""",
        encoding="utf-8",
    )

    with pytest.raises(Exception):
        AgentCardLoader(cards_root).load_all(force_reload=True)


def test_disabled_agent_does_not_participate_in_selection(tmp_path):
    cards_root = tmp_path / "cards"
    cards_root.mkdir()
    (cards_root / "disabled.yaml").write_text(
        """
agent_name: disabled_agent
display_name: Disabled
description: Disabled troubleshooting agent
capabilities:
  - troubleshooting
supported_intents:
  - troubleshooting
required_entities: []
output_schema: SubAgentResult
private_tools: []
public_tools_allowed: true
skills:
  - disabled.default
rag_namespaces: []
memory_policy: {"use_short_summary": true, "recent_turns": 1}
examples: []
enabled: false
version: "1.0.0"
""",
        encoding="utf-8",
    )

    loader = AgentCardLoader(cards_root)
    assert loader.list_available_agents() == []
    assert loader.match_candidates("troubleshooting", {}, "troubleshooting") == []


@pytest.mark.parametrize(
    ("intent", "entities", "query", "expected"),
    [
        ("troubleshooting", {"request_id": "REQ_001"}, "REQ_001 E102 refund failed", "troubleshooting_agent"),
        ("pos_query", {"policy_no": "9201344266"}, "保全实时查询", "pos_query_agent"),
    ],
)
def test_match_candidates_selects_expected_agent(intent, entities, query, expected):
    loader = AgentCardLoader(CARDS_ROOT)
    candidates = loader.match_candidates(intent=intent, entities=entities, query=query)
    assert candidates[0].agent_name == expected


def test_agent_cards_validate_against_skill_catalog():
    loader = AgentCardLoader(CARDS_ROOT)
    loader.validate_with_skill_catalog(SkillCatalog(SKILLS_ROOT))


def test_agent_cards_validate_against_intent_taxonomy():
    loader = AgentCardLoader(CARDS_ROOT)
    taxonomy = IntentTaxonomyLoader().load(force_reload=True)

    loader.validate_with_intent_taxonomy(taxonomy, require_full_coverage=True)


def test_strict_intent_taxonomy_coverage_rejects_uncovered_intent(tmp_path):
    cards_root = tmp_path / "cards"
    _write_minimal_card(cards_root)
    loader = AgentCardLoader(cards_root)
    taxonomy = _taxonomy_with_routes(
        {
            "troubleshooting": ["signature_error"],
            "future_intent": ["future_sub_intent"],
        }
    )

    with pytest.raises(ValueError, match="taxonomy intent has no enabled AgentCard coverage: future_intent"):
        loader.validate_with_intent_taxonomy(taxonomy, require_full_coverage=True)


def test_strict_intent_taxonomy_coverage_rejects_uncovered_sub_intent(tmp_path):
    cards_root = tmp_path / "cards"
    _write_minimal_card(cards_root)
    loader = AgentCardLoader(cards_root)
    taxonomy = _taxonomy_with_routes({"troubleshooting": ["signature_error", "refund_failure"]})

    with pytest.raises(
        ValueError,
        match="taxonomy sub_intent has no enabled AgentCard coverage: troubleshooting.refund_failure",
    ):
        loader.validate_with_intent_taxonomy(taxonomy, require_full_coverage=True)


def test_non_strict_intent_taxonomy_coverage_allows_uncovered_routes(tmp_path):
    cards_root = tmp_path / "cards"
    _write_minimal_card(cards_root)
    loader = AgentCardLoader(cards_root)
    taxonomy = _taxonomy_with_routes(
        {
            "troubleshooting": ["signature_error", "refund_failure"],
            "future_intent": ["future_sub_intent"],
        }
    )

    loader.validate_with_intent_taxonomy(taxonomy, require_full_coverage=False)


def test_disabled_agent_card_does_not_count_as_taxonomy_coverage(tmp_path):
    cards_root = tmp_path / "cards"
    _write_minimal_card(cards_root, filename="enabled.yaml")
    _write_minimal_card(
        cards_root,
        filename="disabled.yaml",
        agent_name="disabled_agent",
        supported_routes="future_intent:\n    - future_sub_intent",
        enabled=False,
    )
    loader = AgentCardLoader(cards_root)
    taxonomy = _taxonomy_with_routes(
        {
            "troubleshooting": ["signature_error"],
            "future_intent": ["future_sub_intent"],
        }
    )

    with pytest.raises(ValueError, match="taxonomy intent has no enabled AgentCard coverage: future_intent"):
        loader.validate_with_intent_taxonomy(taxonomy, require_full_coverage=True)


def test_agent_card_rejects_capability_as_route(tmp_path):
    cards_root = tmp_path / "cards"
    cards_root.mkdir()
    (cards_root / "bad.yaml").write_text(
        """
agent_name: bad_agent
display_name: Bad
description: Bad route
capabilities:
  - internal_log_analysis
supported_routes:
  troubleshooting:
    - internal_log_analysis
required_entities: []
optional_entities: []
output_schema: SubAgentResult
private_tools: []
public_tools_allowed: true
skills: []
rag_namespaces: []
memory_policy: {"use_short_summary": true, "recent_turns": 1}
examples: []
enabled: true
version: "1.0.0"
""",
        encoding="utf-8",
    )
    loader = AgentCardLoader(cards_root)
    taxonomy = IntentTaxonomyLoader().load(force_reload=True)

    with pytest.raises(ValueError, match="invalid sub_intent"):
        loader.validate_with_intent_taxonomy(taxonomy)


def test_agent_card_access_policy_uses_schema(tmp_path):
    cards_root = tmp_path / "cards"
    cards_root.mkdir()
    (cards_root / "secure.yaml").write_text(
        """
agent_name: secure_agent
display_name: Secure
description: Secure agent
capabilities:
  - secure_query
supported_intents:
  - secure_query
required_entities: []
optional_entities: []
output_schema: SubAgentResult
private_tools: []
public_tools_allowed: false
skills: []
rag_namespaces: []
memory_policy: {"use_short_summary": true, "recent_turns": 1}
examples: []
access_policy: {"required_roles": ["manager"], "required_scopes": ["secure:read"], "required_data_permissions": ["secure.sensitive.read"], "allowed_org_types": ["headquarter"], "allowed_org_ids": ["org-1"], "denied_org_ids": ["org-9"]}
enabled: true
version: "1.0.0"
""",
        encoding="utf-8",
    )

    card = AgentCardLoader(cards_root).load_all(force_reload=True)[0]

    assert isinstance(card.access_policy, AgentAccessPolicy)
    assert card.access_policy.required_roles == ["manager"]
    assert card.access_policy.required_scopes == ["secure:read"]
    assert card.access_policy.required_data_permissions == ["secure.sensitive.read"]
    assert card.access_policy.allowed_org_types == ["headquarter"]
    assert card.access_policy.allowed_org_ids == ["org-1"]
    assert card.access_policy.denied_org_ids == ["org-9"]
