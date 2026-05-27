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
        "session_key_created",
        "user_message_saved",
        "original_query",
        "memory_context_loaded",
        "knowledge_hint_loaded",
        "langgraph_node_enter",
        "langgraph_node_exit",
        "agent_cards_loaded",
        "agent_selected",
        "subagent_selected",
        "troubleshooting_started",
        "tool_execution_finished",
        "evidence_built",
        "assistant_message_saved",
        "short_memory_compressed",
        "response_finalized",
        "response_returned",
    }
    assert expected.issubset(event_names)

    contextual_events = [event for event in events if event["event"] in {"request_adapted", "tool_execution_finished"}]
    assert contextual_events
    assert all("request_id" in event for event in contextual_events)
    assert any(event["session_key"] == "pingan_health:web:u001:s001" for event in events)
