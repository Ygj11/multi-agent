"""Runtime Execution Logging 测试。"""

import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.knowledge.in_memory_service import InMemoryKnowledgeService
from app.observability.logger import LOGGER_NAME
from app.schemas.tool import ToolCall
from app.tools.audit_store import ToolCallLogStore
from app.tools.broker import ToolBroker
from app.tools.builtin_tools import build_get_knowledge_tool
from app.tools.policy_gate import PolicyGate
from app.tools.registry import ToolRegistry
from app.tools.shell_exec_tool import ShellExecTool
from app.storage.sqlite import SQLiteDatabase


def _events(caplog) -> list[dict]:
    """从 caplog 中解析 JSON line 日志。"""
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
    """一次 /api/chat 请求应输出完整运行时链路关键事件。"""
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


async def test_shell_exec_rejected_emits_runtime_logs(tmp_path, caplog):
    """shell_exec 被拒绝时也应输出工具链路日志。"""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    db = SQLiteDatabase(tmp_path / "runtime_log.sqlite3")
    registry = ToolRegistry()
    registry.register("shell_exec", ShellExecTool(Path.cwd()))
    broker = ToolBroker(
        registry=registry,
        policy_gate=PolicyGate(Settings(enable_shell_exec=False)),
        audit_store=ToolCallLogStore(db=db),
    )

    result = await broker.call(
        ToolCall(
            name="shell_exec",
            arguments={"command": ["echo", "hello"], "token": "plain-token"},
            session_key="s1",
        )
    )

    assert result.allowed is False
    events = _events(caplog)
    event_names = [event["event"] for event in events]
    assert "tool_call_requested" in event_names
    assert "policy_gate_checked" in event_names
    assert "tool_call_finished" in event_names
    serialized = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
    assert "plain-token" not in serialized
    assert '"token": "***"' in serialized
