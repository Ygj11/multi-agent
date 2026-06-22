from pathlib import Path

import pytest

from app.prompts.loader import PromptLoader, PROMPTS_ROOT


def test_prompt_loader_reads_utf8_and_renders_variables():
    loader = PromptLoader()

    rendered = loader.render(
        "memory_summary/user.md",
        previous_summary="上一轮摘要",
        current_turn="用户继续排查保全任务",
    )

    assert "上一轮摘要" in rendered
    assert "用户继续排查保全任务" in rendered
    assert "不要输出 JSON" in rendered
    assert "保单号" in rendered


def test_prompt_loader_rejects_missing_template():
    loader = PromptLoader()

    with pytest.raises(FileNotFoundError, match="prompt template not found"):
        loader.load("../settings.py")


def test_intent_recognition_prompt_contract():
    system_prompt = PromptLoader().load("intent_recognition/system.md")

    assert "IntentTaxonomy is the only source of legal intent and sub_intent values" in system_prompt
    assert "intent must be one of allowed_intents" in system_prompt
    assert "AgentCard supported_routes describe which agents can handle taxonomy routes" in system_prompt
    assert "Do not use agent_name, skill_id, or capability as intent/sub_intent" in system_prompt
    assert "rewritten_query is the authoritative standalone business request" in system_prompt
    assert "do not redo context inheritance" in system_prompt
    assert "older conversation_window messages mention another intent" in system_prompt
    assert "Never output" in system_prompt
    assert "required_tools" in system_prompt
    assert "Confidence scoring guide" in system_prompt
    assert "Return strict JSON only" in system_prompt


def test_agent_and_skill_router_prompt_contracts_are_candidate_bounded():
    loader = PromptLoader()
    agent_prompt = loader.load("agent_selection/system.md")
    skill_prompt = loader.load("skill_selection/system.md")

    assert "selected_agent must be one of the candidate agent_name values" in agent_prompt
    assert "Query is the rewritten standalone business request" in agent_prompt
    assert "Use the provided intent and sub_intent as primary routing signals" in agent_prompt
    assert "Do not select an agent because of a tool name" in agent_prompt
    assert "Do not reject a candidate only because required_entities are missing" in agent_prompt
    assert "Do not use full skill bodies" in agent_prompt
    assert "Do not use full tool schemas" in agent_prompt
    assert "selected_skill_id must be one of the candidate skill_id values" in skill_prompt
    assert "Use only skill metadata" in skill_prompt
    assert "Do not request or assume full SKILL.md bodies" in skill_prompt


def test_subagent_reasoning_prompt_has_enterprise_tool_constraints():
    prompt = PromptLoader().load("subagent_reasoning/system.md")

    assert "Never invent, assume, or simulate tool results" in prompt
    assert "If a tool returns an error" in prompt
    assert "Write, notify, update, submit, recovery, or side-effect tools" in prompt
    assert "Do not output raw internal logs, full tool JSON" in prompt
    assert "Final answer structure" in prompt


def test_all_prompt_files_are_utf8_readable():
    for path in Path(PROMPTS_ROOT).rglob("*.md"):
        content = path.read_text(encoding="utf-8")
        assert content.strip(), f"{path} must not be empty"
