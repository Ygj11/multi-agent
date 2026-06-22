"""Runtime execution logging tests."""

import json
import logging

from fastapi.testclient import TestClient

from app.observability.logger import LOGGER_NAME


def _events(caplog) -> list[dict]:
    events = []
    for record in caplog.records:
        if record.name != LOGGER_NAME:
            continue
        try:
            events.append(json.loads(record.getMessage()))
        except json.JSONDecodeError:
            continue
    return events


def test_api_chat_emits_runtime_execution_events(app_factory, caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    app = app_factory()
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "tenant_id": "pingan_health",
            "channel": "web",
            "user_id": "u001",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "REQ_001 为什么返回 E102？"}],
        },
    )

    assert response.status_code == 200
    events = _events(caplog)
    event_names = {event["event"] for event in events}

    expected = {
        "request_received",
        "request_adapted",
        "user_message_saved",
        "memory_context_loaded",
        "knowledge_hint_loaded",
        "agent_cards_loaded",
        "agent_selected",
        "subagent_selected",
        "skill_no_match_blocked",
        "assistant_message_saved",
        "short_memory_compressed",
        "response_finalized",
        "response_returned",
    }
    assert expected.issubset(event_names)
    assert "session_key_created" not in event_names
    assert "original_query" not in event_names
    assert "langgraph_node_enter" not in event_names
    assert "langgraph_node_exit" not in event_names

    contextual_events = [event for event in events if event["event"] in {"request_adapted", "skill_no_match_blocked"}]
    assert contextual_events
    assert all("request_id" in event for event in contextual_events)
    assert any(event["session_key"] == "pingan_health:web:u001:s001" for event in events)
    assert any(event["event"] == "llm_chat_finished" and event["trace_id"] for event in events)
