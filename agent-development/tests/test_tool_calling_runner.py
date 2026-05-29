from app.llm.schemas import LLMResponse
from app.schemas.agent_card import AgentCard
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


async def _tool1(value: str = ""):
    return {"tool": "tool1", "value": value}


async def _tool2(value: str = ""):
    return {"tool": "tool2", "value": value}


async def _failing_tool(value: str = ""):
    return {"success": False, "error": f"failed:{value}"}


class SequencedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, "kwargs": kwargs})
        return self.responses.pop(0)


def _runner(responses):
    registry = ToolRegistry()
    registry.register_private(agent_name="agent_a", name="tool1", tool=_tool1)
    registry.register_private(agent_name="agent_a", name="tool2", tool=_tool2)
    registry.register_private(agent_name="agent_a", name="failing_tool", tool=_failing_tool)
    executor = ToolExecutor(registry=registry)
    llm = SequencedLLM(responses)
    return ToolCallingRunner(llm_provider=llm, tool_executor=executor), llm


def _card():
    return AgentCard(
        agent_name="agent_a",
        display_name="Agent A",
        description="test",
        capabilities=["test"],
        supported_intents=["test"],
        required_entities=[],
        output_schema="SubAgentResult",
        private_tools=["tool1", "tool2", "failing_tool"],
        public_tools_allowed=False,
        skills=["agent_a.default"],
        rag_namespaces=[],
        enabled=True,
        version="1",
    )


async def test_runner_executes_multiple_tool_rounds_and_returns_final_answer():
    runner, llm = _runner(
        [
            LLMResponse(content=None, tool_calls=[{"name": "tool1", "arguments": {"value": "a"}}], has_tool_calls=True),
            LLMResponse(content=None, tool_calls=[{"name": "tool2", "arguments": {"value": "b"}}], has_tool_calls=True),
            LLMResponse(content="final answer", tool_calls=[], has_tool_calls=False),
        ]
    )

    result = await runner.run(
        agent_name="agent_a",
        agent_card=_card(),
        messages=[{"role": "user", "content": "go"}],
        tools=[],
        session_key="s",
        request_id="r",
    )

    assert result.final_answer == "final answer"
    assert result.stopped_reason == "final"
    assert result.iterations == 3
    assert [message["role"] for message in result.messages].count("tool") == 2
    assert llm.calls[0]["kwargs"]["scene"] == "subagent_reasoning"


async def test_runner_returns_error_on_llm_error():
    runner, _ = _runner([LLMResponse(content=None, finish_reason="error", error="boom")])

    result = await runner.run(
        agent_name="agent_a",
        agent_card=_card(),
        messages=[{"role": "user", "content": "go"}],
        tools=[],
        session_key="s",
        request_id="r",
    )

    assert result.stopped_reason == "error"
    assert result.error == "boom"


async def test_runner_returns_max_iterations():
    runner, _ = _runner([LLMResponse(content=None, tool_calls=[{"name": "tool1", "arguments": {}}], has_tool_calls=True)])

    result = await runner.run(
        agent_name="agent_a",
        agent_card=_card(),
        messages=[{"role": "user", "content": "go"}],
        tools=[],
        session_key="s",
        request_id="r",
        max_iterations=1,
    )

    assert result.stopped_reason == "max_iterations"
    assert "max_iterations" in result.error


async def test_runner_adds_observation_for_tool_failure_and_parse_error():
    runner, _ = _runner(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    {"name": "other_agent_tool", "arguments": {}},
                    {"name": "tool1", "arguments": "{bad json"},
                ],
                has_tool_calls=True,
            ),
            LLMResponse(content="fixed", has_tool_calls=False),
        ]
    )

    result = await runner.run(
        agent_name="agent_a",
        agent_card=_card(),
        messages=[{"role": "user", "content": "go"}],
        tools=[],
        session_key="s",
        request_id="r",
    )

    assert result.stopped_reason == "final"
    assert any(call.get("error") == "tool_not_found" for call in result.tool_calls)
    assert any(call.get("error", "").startswith("tool_arguments_invalid_json") for call in result.tool_calls)
    assert [message["role"] for message in result.messages].count("tool") == 2


async def test_runner_stops_on_duplicate_tool_call_limit():
    runner, _ = _runner(
        [
            LLMResponse(content=None, tool_calls=[{"name": "tool1", "arguments": {"value": "same"}}], has_tool_calls=True),
            LLMResponse(content=None, tool_calls=[{"name": "tool1", "arguments": {"value": "same"}}], has_tool_calls=True),
            LLMResponse(content=None, tool_calls=[{"name": "tool1", "arguments": {"value": "same"}}], has_tool_calls=True),
        ]
    )
    runner.max_duplicate_tool_calls = 2

    result = await runner.run(
        agent_name="agent_a",
        agent_card=_card(),
        messages=[{"role": "user", "content": "loop"}],
        tools=[],
        session_key="s",
        request_id="r",
        max_iterations=5,
    )

    assert result.stopped_reason == "max_duplicate_tool_calls"
    assert result.error == "max_duplicate_tool_calls"
    assert result.tool_calls[-1]["error"] == "max_duplicate_tool_calls"


async def test_runner_stops_on_consecutive_tool_failures():
    runner, _ = _runner(
        [
            LLMResponse(content=None, tool_calls=[{"name": "failing_tool", "arguments": {"value": "a"}}], has_tool_calls=True),
            LLMResponse(content=None, tool_calls=[{"name": "failing_tool", "arguments": {"value": "b"}}], has_tool_calls=True),
        ]
    )
    runner.max_consecutive_tool_failures = 2
    runner.max_same_tool_failures = 10
    runner.max_duplicate_tool_calls = 10

    result = await runner.run(
        agent_name="agent_a",
        agent_card=_card(),
        messages=[{"role": "user", "content": "fail"}],
        tools=[],
        session_key="s",
        request_id="r",
        max_iterations=5,
    )

    assert result.stopped_reason == "max_consecutive_tool_failures"
    assert result.error == "max_consecutive_tool_failures"


async def test_runner_stops_on_same_tool_same_arguments_failures():
    runner, _ = _runner(
        [
            LLMResponse(content=None, tool_calls=[{"name": "failing_tool", "arguments": {"value": "same"}}], has_tool_calls=True),
            LLMResponse(content=None, tool_calls=[{"name": "failing_tool", "arguments": {"value": "same"}}], has_tool_calls=True),
        ]
    )
    runner.max_consecutive_tool_failures = 10
    runner.max_same_tool_failures = 2
    runner.max_duplicate_tool_calls = 10

    result = await runner.run(
        agent_name="agent_a",
        agent_card=_card(),
        messages=[{"role": "user", "content": "fail same"}],
        tools=[],
        session_key="s",
        request_id="r",
        max_iterations=5,
    )

    assert result.stopped_reason == "max_same_tool_failures"
    assert result.error == "max_same_tool_failures"


async def test_runner_stops_missing_required_argument_loop():
    registry = ToolRegistry()

    async def required_tool(apply_seq: str | None = None):
        return {"apply_seq": apply_seq}

    registry.register_private(
        agent_name="agent_a",
        name="query_endo_task_record",
        tool=required_tool,
        parameters={
            "type": "object",
            "properties": {"apply_seq": {"type": "string", "description": "Apply sequence."}},
            "required": ["apply_seq"],
        },
    )
    executor = ToolExecutor(registry=registry)
    llm = SequencedLLM(
        [
            LLMResponse(content=None, tool_calls=[{"name": "query_endo_task_record", "arguments": {}}], has_tool_calls=True),
            LLMResponse(content=None, tool_calls=[{"name": "query_endo_task_record", "arguments": {}}], has_tool_calls=True),
        ]
    )
    runner = ToolCallingRunner(
        llm_provider=llm,
        tool_executor=executor,
        max_consecutive_tool_failures=2,
        max_same_tool_failures=10,
        max_duplicate_tool_calls=10,
    )
    card = _card().model_copy(update={"private_tools": ["query_endo_task_record"]})

    result = await runner.run(
        agent_name="agent_a",
        agent_card=card,
        messages=[{"role": "user", "content": "missing"}],
        tools=[],
        session_key="s",
        request_id="r",
        max_iterations=5,
    )

    assert result.stopped_reason == "max_consecutive_tool_failures"
    assert result.tool_calls[0]["error"] == "missing_required_argument:apply_seq"
