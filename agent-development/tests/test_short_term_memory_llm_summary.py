import inspect

from app.llm.schemas import LLMResponse
from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.storage.sqlite import SQLiteDatabase


class CapturingLLM:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.calls: list[dict] = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        return LLMResponse(content=self.content)


class RaisingLLM:
    async def chat(self, messages, tools=None, **kwargs):
        raise RuntimeError("llm down")


async def _set_previous_summary(db: SQLiteDatabase, session_key: str, summary: str) -> None:
    def write(conn):
        conn.execute(
            """
            INSERT INTO short_term_memory(session_key, summary, updated_at)
            VALUES (?, ?, '2026-01-01T00:00:00Z')
            """,
            (session_key, summary),
        )

    await db.run(write)


async def _table_columns(db: SQLiteDatabase) -> list[str]:
    def read(conn):
        return [row["name"] for row in conn.execute("PRAGMA table_info(short_term_memory)").fetchall()]

    return await db.run(read)


async def test_llm_summary_saved_when_valid(tmp_path):
    db = SQLiteDatabase(tmp_path / "memory.sqlite3")
    llm_summary = "用户正在排查 REQ_001 在 submitProposal 接口返回 E102 的签名校验失败问题，已知需要重点检查 timestamp 是否参与签名、密钥版本和字段排序。下一轮如果用户说继续或谁的问题，应指代这个请求的签名失败排查。"
    llm = CapturingLLM(llm_summary)
    manager = ShortTermMemoryManager(db=db, llm_provider=llm)

    summary = await manager.compress_after_turn(
        session_key="s1",
        original_query="REQ_001 为什么 E102？",
        rewritten_query="排查 requestId=REQ_001 的 E102 错误原因",
        intent="troubleshooting",
        answer="初步是签名校验失败。",
        subagent_result={"agent_name": "troubleshooting_agent", "selected_skill_id": "troubleshooting_agent.signature_error"},
    )

    assert summary == llm_summary
    assert await manager.get_summary("s1") == llm_summary
    assert llm.calls[0]["kwargs"]["scene"] == "summary"
    assert llm.calls[0]["tools"] is None


async def test_previous_summary_and_current_turn_are_sent_to_llm(tmp_path):
    db = SQLiteDatabase(tmp_path / "memory.sqlite3")
    await _set_previous_summary(db, "s1", "上一轮在看保单 P2021344266 的退保失败。")
    llm = CapturingLLM("承接上一轮，用户继续排查保单 P2021344266 的退保失败，本轮补充了 REQ_001 和 E102，当前结论是签名校验失败，尚需确认密钥版本。")
    manager = ShortTermMemoryManager(db=db, llm_provider=llm)

    await manager.compress_after_turn(
        session_key="s1",
        original_query="继续看 REQ_001",
        rewritten_query="继续排查 REQ_001",
        intent="troubleshooting",
        answer="发现 E102。",
        subagent_result={"diagnosis": "签名失败", "tool_calls": [{"name": "query_internal_log"}]},
    )

    prompt = llm.calls[0]["messages"][1]["content"]
    assert "previous_summary:" in prompt
    assert "上一轮在看保单 P2021344266 的退保失败。" in prompt
    assert "current_turn:" in prompt
    assert "- original_query: 继续看 REQ_001" in prompt
    assert "- rewritten_query: 继续排查 REQ_001" in prompt
    assert "- intent: troubleshooting" in prompt
    assert "- answer: 发现 E102。" in prompt
    assert "subagent_result_summary" in prompt


async def test_llm_exception_falls_back_to_rule_summary(tmp_path):
    db = SQLiteDatabase(tmp_path / "memory.sqlite3")
    manager = ShortTermMemoryManager(db=db, llm_provider=RaisingLLM())

    summary = await manager.compress_after_turn(
        session_key="s1",
        original_query="REQ_001 为什么 E102？",
        rewritten_query="排查 requestId=REQ_001 的健康险个险接口 E102 错误原因",
        intent="troubleshooting",
        answer="submitProposal 签名校验失败。",
    )

    assert "requestId=REQ_001" in summary
    assert "E102" in summary
    assert await manager.get_summary("s1") == summary


async def test_empty_llm_summary_falls_back_to_rules(tmp_path):
    db = SQLiteDatabase(tmp_path / "memory.sqlite3")
    manager = ShortTermMemoryManager(db=db, llm_provider=CapturingLLM("   "))

    summary = await manager.compress_after_turn(
        session_key="s1",
        original_query="保单状态是什么？",
        rewritten_query="查询保单状态",
        intent="policy_query",
        answer="保单有效。",
    )

    assert summary == "上一轮意图为 policy_query，用户问题是：保单状态是什么？"


async def test_json_like_llm_summary_falls_back_and_result_is_str(tmp_path):
    db = SQLiteDatabase(tmp_path / "memory.sqlite3")
    manager = ShortTermMemoryManager(db=db, llm_provider=CapturingLLM('{"summary":"不要用 JSON"}'))

    summary = await manager.compress_after_turn(
        session_key="s1",
        original_query="理赔进度",
        rewritten_query="查询理赔进度",
        intent="claim_query",
        answer="理赔处理中。",
    )

    assert isinstance(summary, str)
    assert not summary.strip().startswith("{")
    assert summary == "上一轮意图为 claim_query，用户问题是：理赔进度"


async def test_short_term_memory_table_schema_unchanged(tmp_path):
    db = SQLiteDatabase(tmp_path / "memory.sqlite3")

    assert await _table_columns(db) == ["session_key", "summary", "updated_at"]


def test_compress_after_turn_does_not_accept_recent_messages():
    parameters = inspect.signature(ShortTermMemoryManager.compress_after_turn).parameters

    assert "recent_messages" not in parameters
