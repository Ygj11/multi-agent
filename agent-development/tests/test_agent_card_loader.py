from pathlib import Path

import pytest

from app.agents.card_loader import AgentCardLoader
from app.skills.catalog import SkillCatalog


CARDS_ROOT = Path("app/agents/cards")
SKILLS_ROOT = Path("app/skills")


def test_agent_card_yaml_loads_required_fields():
    loader = AgentCardLoader(CARDS_ROOT)
    cards = {card.agent_name: card for card in loader.load_all(force_reload=True)}

    assert "troubleshooting_agent" in cards
    card = cards["troubleshooting_agent"]
    assert card.display_name
    assert "query_internal_log" in card.private_tools
    assert card.public_tools_allowed is True
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
        ("policy_query", {"policy_no": "9201344266"}, "policy status", "policy_query_agent"),
        ("claim_query", {"claim_no": "CLM_001"}, "claim progress", "claim_agent"),
        ("compliance_review", {}, "privacy token secret outbound review", "compliance_agent"),
    ],
)
def test_match_candidates_selects_expected_agent(intent, entities, query, expected):
    loader = AgentCardLoader(CARDS_ROOT)
    candidates = loader.match_candidates(intent=intent, entities=entities, query=query)
    assert candidates[0].agent_name == expected


def test_agent_cards_validate_against_skill_catalog():
    loader = AgentCardLoader(CARDS_ROOT)
    loader.validate_with_skill_catalog(SkillCatalog(SKILLS_ROOT))
