from __future__ import annotations

from app.evidence.builder import EvidenceBuilder
from app.evidence.store import EvidenceStore
from app.knowledge.schemas import KnowledgeChunk
from app.storage.sqlite import SQLiteDatabase
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.tool_execution_log_store import ToolExecutionLogStore


async def test_evidence_store_saves_summary_and_tool_log_reference(tmp_path):
    store = EvidenceStore(SQLiteDatabase(tmp_path / "evidence.sqlite3"))
    evidence = EvidenceBuilder.from_tool_result(
        session_key="s1",
        request_id="req1",
        tool_name="query_internal_log",
        result={"request_id": "REQ_001", "error_code": "E102"},
        tool_log_id=7,
    )

    await store.save(evidence)
    items = await store.list_by_request("req1")

    assert len(items) == 1
    assert items[0].source_type == "tool"
    assert items[0].tool_log_id == 7
    assert "REQ_001" in str(items[0].summary)
    assert not hasattr(items[0], "content")
    assert not hasattr(items[0], "redactions")


async def test_evidence_table_does_not_store_full_content_json(tmp_path):
    db = SQLiteDatabase(tmp_path / "evidence-schema.sqlite3")

    def read_columns(conn):
        return [row["name"] for row in conn.execute("PRAGMA table_info(evidence)").fetchall()]

    columns = await db.run(read_columns)

    assert "tool_log_id" in columns
    assert "content_json" not in columns
    assert "redactions_json" not in columns


def test_evidence_builder_creates_knowledge_citation():
    chunk = KnowledgeChunk(
        content="rule content",
        source="doc-a",
        score=0.9,
        metadata={"namespace": "policy"},
    )

    evidence = EvidenceBuilder.from_knowledge_chunk(session_key="s1", request_id="req1", chunk=chunk)

    assert evidence.source_type == "knowledge"
    assert evidence.citations[0]["source"] == "doc-a"
    assert evidence.citations[0]["metadata"]["namespace"] == "policy"


async def test_tool_executor_writes_tool_result_evidence(tmp_path):
    async def sample_tool(request_id: str):
        return {"request_id": request_id, "status": "failed"}

    db = SQLiteDatabase(tmp_path / "tool-evidence.sqlite3")
    log_store = ToolExecutionLogStore(db)
    evidence_store = EvidenceStore(db)
    registry = ToolRegistry()
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="query_task_status",
        tool=sample_tool,
        parameters={
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "required": ["request_id"],
        },
    )
    executor = ToolExecutor(registry=registry, log_store=log_store, evidence_store=evidence_store)

    result = await executor.execute(
        agent_name="troubleshooting_agent",
        tool_name="query_task_status",
        arguments={"request_id": "REQ_001"},
        request_id="req1",
        trace_id="trace1",
        session_key="s1",
    )

    items = await evidence_store.list_by_request("req1")
    assert result.success is True
    assert len(items) == 1
    assert items[0].source_type == "tool"
    assert items[0].tool_log_id is not None
    assert "failed" in str(items[0].summary)

    log = await log_store.get_by_id(items[0].tool_log_id)
    assert log is not None
    assert log["tool_name"] == "query_task_status"
    assert log["success"] is True
    assert log["result"]["status"] == "failed"
