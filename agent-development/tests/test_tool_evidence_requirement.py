from pathlib import Path

from app.agents.card_loader import AgentCardLoader
from app.llm.schemas import LLMResponse
from app.runtime.context_builder import ContextBuilder
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.subagents.troubleshooting_agent import TroubleshootingAgent
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class SequencedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, "kwargs": kwargs})
        return self.responses.pop(0)


def _entities() -> dict[str, str]:
    return {
        "apply_seq": "930021042875719",
        "policy_no": "9200100000458846",
        "endorseType": "001028",
    }


def _task() -> SubAgentTask:
    return SubAgentTask(
        agent_name="troubleshooting_agent",
        agent_card_version="1.0.0",
        query="保全任务完成，保单没有更新",
        original_query="保全任务完成，保单没有更新",
        intent="troubleshooting",
        session_key="s-tool-evidence",
        request_id="req-tool-evidence",
        entities=_entities(),
    )


def _parent_context(task: SubAgentTask) -> OrchestratorContext:
    return OrchestratorContext(
        original_query=task.original_query,
        rewritten_query=task.query,
        intent=task.intent,
        sub_intent="endo_completion_aftercare",
        entities=task.entities,
        session_key=task.session_key,
    )


def _agent(responses: list[LLMResponse]) -> tuple[TroubleshootingAgent, SequencedLLM]:
    registry = ToolRegistry()

    async def query_endo_task_record(apply_seq: str):
        return {"apply_seq": apply_seq, "status": "failed"}

    registry.register_private(
        agent_name="troubleshooting_agent",
        name="query_endo_task_record",
        tool=query_endo_task_record,
        description="查询保全任务记录。",
        parameters={
            "type": "object",
            "properties": {"apply_seq": {"type": "string", "description": "保全受理号。"}},
            "required": ["apply_seq"],
        },
    )
    llm = SequencedLLM(responses)
    skills_root = Path("app/skills")
    context_builder = ContextBuilder(
        skills_root=skills_root,
        skill_catalog=SkillCatalog(skills_root),
        skill_selector=SkillSelector(),
    )
    return (
        TroubleshootingAgent(
            context_builder=context_builder,
            agent_card_loader=AgentCardLoader(Path("app/agents/cards")),
            tool_executor=ToolExecutor(registry),
            tool_calling_runner=ToolCallingRunner(llm_provider=llm, tool_executor=ToolExecutor(registry)),
        ),
        llm,
    )


async def test_required_tool_evidence_turns_missing_tool_argument_into_clarification():
    agent, llm = _agent(
        [
            LLMResponse(
                content=None,
                has_tool_calls=True,
                tool_calls=[{"name": "query_endo_task_record", "arguments": {}}],
            ),
            LLMResponse(content="保全任务已经处理完成。", has_tool_calls=False),
        ]
    )
    task = _task()

    result = await agent.run(task, _parent_context(task))

    assert result.metadata["clarification"] is True
    assert result.metadata["clarification_source"] == "tool_evidence_required"
    assert result.metadata["missing_tool_arguments"] == [
        {"tool_name": "query_endo_task_record", "arguments": ["apply_seq"]}
    ]
    assert "保全受理号" in result.answer
    assert result.answer != "保全任务已经处理完成。"
    assert result.tool_calls[0]["missing_required_arguments"] == ["apply_seq"]
    assert "true" in llm.calls[0]["messages"][0]["content"]


async def test_required_tool_evidence_blocks_free_text_when_no_tool_was_called():
    agent, _ = _agent([LLMResponse(content="我判断问题已经解决。", has_tool_calls=False)])
    task = _task()

    result = await agent.run(task, _parent_context(task))

    assert result.metadata["clarification"] is True
    assert result.metadata["clarification_source"] == "tool_evidence_required"
    assert result.metadata["missing_tool_arguments"] == []
    assert result.answer != "我判断问题已经解决。"


async def test_required_tool_evidence_allows_final_answer_after_successful_tool_result():
    agent, _ = _agent(
        [
            LLMResponse(
                content=None,
                has_tool_calls=True,
                tool_calls=[{"name": "query_endo_task_record", "arguments": {"apply_seq": _entities()["apply_seq"]}}],
            ),
            LLMResponse(content="查询到任务节点失败，需要继续处理。", has_tool_calls=False),
        ]
    )
    task = _task()

    result = await agent.run(task, _parent_context(task))

    assert result.metadata.get("clarification") is None
    assert result.answer == "查询到任务节点失败，需要继续处理。"
    assert result.tool_calls[0]["success"] is True
