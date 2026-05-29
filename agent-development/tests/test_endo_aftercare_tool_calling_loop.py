from app.llm.schemas import LLMResponse
from app.schemas.agent_card import AgentCard
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.agent_tools import register_agent_private_tools
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class SequencedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, "kwargs": kwargs})
        return self.responses.pop(0)


def _card():
    return AgentCard(
        agent_name="troubleshooting_agent",
        display_name="Troubleshooting Agent",
        description="test",
        capabilities=["endo_completion_aftercare"],
        supported_intents=["troubleshooting"],
        required_entities=[],
        output_schema="SubAgentResult",
        private_tools=[
            "query_endo_task_record",
            "notice_policy_update",
            "notice_customer_update",
            "notice_period_update",
            "policy_suspendOrRecovery",
            "notice_finance",
        ],
        public_tools_allowed=False,
        skills=["troubleshooting_agent.endo_completion_aftercare"],
        rag_namespaces=[],
        enabled=True,
        version="1",
    )


async def test_endo_aftercare_tool_calling_loop_policy_update_requires_approval():
    registry = ToolRegistry()
    register_agent_private_tools(registry)
    llm = SequencedLLM(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_query_endo",
                        "function": {
                            "name": "query_endo_task_record",
                            "arguments": '{"apply_seq": "APPLY_POLICY_UPDATE_FAIL"}',
                        },
                    }
                ],
                has_tool_calls=True,
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_notice_policy",
                        "function": {
                            "name": "notice_policy_update",
                            "arguments": '{"apply_seq": "APPLY_POLICY_UPDATE_FAIL", "policyNo": "P001", "endorseType": "退保"}',
                        },
                    }
                ],
                has_tool_calls=True,
                finish_reason="tool_calls",
            ),
        ]
    )
    runner = ToolCallingRunner(llm_provider=llm, tool_executor=ToolExecutor(registry))
    card = _card()

    result = await runner.run(
        agent_name="troubleshooting_agent",
        agent_card=card,
        messages=[{"role": "user", "content": "保全任务完成但是保单信息没有更新"}],
        tools=registry.list_tools_for_agent(card),
        session_key="s",
        request_id="r",
    )

    assert result.stopped_reason == "human_approval_required"
    assert result.needs_human_approval is True
    assert [call["name"] for call in result.tool_calls] == ["query_endo_task_record", "notice_policy_update"]
    assert "保单更新错误" in str(result.tool_calls[0]["result"])
    assert result.tool_calls[1]["success"] is False
    assert result.tool_calls[1]["error"] == "human_approval_required"
    assert result.pending_tool_call["name"] == "notice_policy_update"
