from app.llm.schemas import LLMResponse
from app.schemas.agent_card import AgentCard
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


async def _tool1(value: str = ""):
    return {"tool": "tool1", "value": value}


async def _tool2(value: str = ""):
    return {"tool": "tool2", "value": value}


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
        private_tools=["tool1", "tool2"],
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

