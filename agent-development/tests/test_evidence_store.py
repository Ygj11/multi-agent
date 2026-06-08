from __future__ import annotations

from app.evidence.builder import EvidenceBuilder
from app.evidence.store import EvidenceStore
from app.knowledge.schemas import KnowledgeChunk
from app.storage.sqlite import SQLiteDatabase
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


async def test_evidence_store_saves_and_lists_tool_evidence(tmp_path):
    store = EvidenceStore(SQLiteDatabase(tmp_path / "evidence.sqlite3"))
    evidence = EvidenceBuilder.from_tool_result(
        session_key="s1",
        request_id="req1",
        tool_name="query_internal_log",
        result={"request_id": "REQ_001", "error_code": "E102"},
    )

    await store.save(evidence)
    items = await store.list_by_request("req1")

    assert len(items) == 1
    assert items[0].source_type == "tool"
    assert items[0].content["request_id"] == "REQ_001"


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
    executor = ToolExecutor(registry=registry, evidence_store=evidence_store)

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
    assert items[0].content["name"] == "query_task_status"
    assert items[0].content["result"]["status"] == "failed"
