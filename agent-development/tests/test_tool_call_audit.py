"""工具调用审计日志测试。"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.knowledge.in_memory_service import InMemoryKnowledgeService
from app.mcp.fake_connector import FakeMCPConnector
from app.schemas.tool import ToolCall
from app.storage.sqlite import SQLiteDatabase
from app.tools.audit_store import ToolCallLogStore
from app.tools.broker import ToolBroker
from app.tools.builtin_tools import build_get_knowledge_tool, query_internal_log
from app.tools.mcp_tools import build_mcp_tool
from app.tools.policy_gate import PolicyGate
from app.tools.registry import ToolRegistry
from app.tools.shell_exec_tool import ShellExecTool


def _broker(tmp_path: Path, enable_shell_exec: bool = False) -> tuple[ToolBroker, ToolCallLogStore]:
    """创建带审计 store 的 ToolBroker。"""
    db = SQLiteDatabase(tmp_path / "audit.sqlite3")
    audit_store = ToolCallLogStore(db=db)
    registry = ToolRegistry()
    registry.register("query_internal_log", query_internal_log)
    registry.register("get_knowledge", build_get_knowledge_tool(InMemoryKnowledgeService()))
    registry.register(
        "partner_trace.get_request_detail",
        build_mcp_tool(FakeMCPConnector(), "partner_trace.get_request_detail"),
    )
    registry.register("shell_exec", ShellExecTool(project_root=Path.cwd()))
    broker = ToolBroker(
        registry=registry,
        policy_gate=PolicyGate(Settings(enable_shell_exec=enable_shell_exec)),
        audit_store=audit_store,
    )
    return broker, audit_store


async def test_query_internal_log_success_writes_audit(tmp_path):
    """query_internal_log 成功调用应写入 tool_call_logs。"""
    broker, audit_store = _broker(tmp_path)
    result = await broker.call(
        ToolCall(
            name="query_internal_log",
            arguments={"request_id": "REQ_001"},
            request_id="req_audit",
            trace_id="trace_audit",
            session_key="s1",
        )
    )

    logs = await audit_store.list_by_session("s1")
    assert result.success is True
    assert logs[0]["tool_name"] == "query_internal_log"
    assert logs[0]["allowed"] is True
    assert logs[0]["success"] is True
    assert logs[0]["request_id"] == "req_audit"
    assert logs[0]["trace_id"] == "trace_audit"


async def test_get_knowledge_success_writes_audit(tmp_path):
    """get_knowledge 成功调用应写入 tool_call_logs。"""
    broker, audit_store = _broker(tmp_path)
    await broker.call(
        ToolCall(
            name="get_knowledge",
            arguments={"query": "E102", "top_k": 1},
            request_id="req_knowledge",
            trace_id="trace_knowledge",
            session_key="s1",
        )
    )

    logs = await audit_store.list_by_session("s1")
    assert logs[0]["tool_name"] == "get_knowledge"
    assert "E102" in (logs[0]["result_json"] or "")


async def test_mcp_tool_success_writes_audit(tmp_path):
    """partner_trace.get_request_detail 成功调用应写入审计日志。"""
    broker, audit_store = _broker(tmp_path)
    await broker.call(
        ToolCall(
            name="partner_trace.get_request_detail",
            arguments={"request_id": "REQ_001"},
            request_id="req_mcp",
            trace_id="trace_mcp",
            session_key="s1",
        )
    )

    logs = await audit_store.list_by_session("s1")
    assert logs[0]["tool_name"] == "partner_trace.get_request_detail"
    assert logs[0]["allowed"] is True
    assert logs[0]["success"] is True
    assert "旧版" in (logs[0]["result_json"] or "")


async def test_shell_exec_rejected_writes_audit(tmp_path):
    """shell_exec 默认被拒绝时也应写入审计日志。"""
    broker, audit_store = _broker(tmp_path, enable_shell_exec=False)
    result = await broker.call(
        ToolCall(
            name="shell_exec",
            arguments={"command": ["echo", "hello"]},
            request_id="req_shell",
            trace_id="trace_shell",
            session_key="s1",
        )
    )

    logs = await audit_store.list_by_session("s1")
    assert result.allowed is False
    assert logs[0]["tool_name"] == "shell_exec"
    assert logs[0]["allowed"] is False
    assert logs[0]["success"] is False
    assert "disabled" in logs[0]["error"]


async def test_shell_exec_allowed_writes_audit(tmp_path):
    """shell_exec allowlist 命令执行成功时应写入审计日志。"""
    broker, audit_store = _broker(tmp_path, enable_shell_exec=True)
    result = await broker.call(
        ToolCall(
            name="shell_exec",
            arguments={"command": ["echo", "hello"]},
            request_id="req_shell",
            trace_id="trace_shell",
            session_key="s1",
        )
    )

    logs = await audit_store.list_by_session("s1")
    assert result.success is True
    assert logs[0]["allowed"] is True
    assert logs[0]["success"] is True
    assert "hello" in (logs[0]["result_json"] or "")


async def test_shell_exec_non_allowlisted_writes_audit(tmp_path):
    """shell_exec 非 allowlist 命令被拒绝时应写入审计日志。"""
    broker, audit_store = _broker(tmp_path, enable_shell_exec=True)
    await broker.call(
        ToolCall(
            name="shell_exec",
            arguments={"command": ["rm", "-rf", "."]},
            request_id="req_shell",
            trace_id="trace_shell",
            session_key="s1",
        )
    )

    logs = await audit_store.list_by_session("s1")
    assert logs[0]["allowed"] is False
    assert logs[0]["success"] is False
    assert "allowlisted" in logs[0]["error"]


async def test_audit_masks_sensitive_arguments(tmp_path):
    """arguments_json 不应保存敏感字段明文。"""
    broker, audit_store = _broker(tmp_path)
    await broker.call(
        ToolCall(
            name="get_knowledge",
            arguments={"query": "E102", "token": "plain-token", "password": "plain-password"},
            session_key="s1",
        )
    )

    logs = await audit_store.list_by_session("s1")
    arguments = json.loads(logs[0]["arguments_json"])
    assert arguments["token"] == "***"
    assert arguments["password"] == "***"
    assert "plain-token" not in logs[0]["arguments_json"]


async def test_tool_logs_are_isolated_by_session_key(tmp_path):
    """不同 session_key 的工具日志应隔离读取。"""
    broker, audit_store = _broker(tmp_path)
    await broker.call(
        ToolCall(name="get_knowledge", arguments={"query": "E102"}, session_key="session_a")
    )
    await broker.call(
        ToolCall(name="get_knowledge", arguments={"query": "E102"}, session_key="session_b")
    )

    logs_a = await audit_store.list_by_session("session_a")
    logs_b = await audit_store.list_by_session("session_b")
    assert len(logs_a) == 1
    assert len(logs_b) == 1
    assert logs_a[0]["session_key"] == "session_a"
    assert logs_b[0]["session_key"] == "session_b"


async def test_api_chat_req_001_writes_three_tool_logs(app_factory):
    """/api/chat 一次 REQ_001 后应写入三条核心工具审计日志。"""
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
    logs = await app.state.tool_call_log_store.list_by_session("pingan_health:web:u001:s001")
    tool_names = {log["tool_name"] for log in logs}
    assert {"query_internal_log", "get_knowledge", "partner_trace.get_request_detail"}.issubset(tool_names)
    assert all(log["session_key"] == "pingan_health:web:u001:s001" for log in logs)
