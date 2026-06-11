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


class FakeTroubleshootingAPIClient:
    async def query_task_status(self, request_id=None):
        return {"request_id": request_id, "status": "failed"}

    async def query_node_status(self, request_id=None, node_name=None):
        return {"request_id": request_id, "node_name": node_name, "status": "error"}

    async def query_internal_log(self, request_id=None, query=None):
        return {"request_id": request_id, "query": query, "found": True}

    async def query_endo_task_record(self, apply_seq=None):
        return {
            "apply_seq": apply_seq,
            "records": [{"task_type": "9", "task_status": "E", "response_body": "保单更新错误：real fake"}],
            "success": True,
        }

    async def notice_policy_update(self, **kwargs):
        return {"success": True, "payload": kwargs}

    async def notice_customer_update(self, **kwargs):
        return {"success": True, "payload": kwargs}

    async def notice_period_update(self, **kwargs):
        return {"success": True, "payload": kwargs}

    async def policy_suspend_or_recovery(self, **kwargs):
        return {"success": True, "payload": kwargs}

    async def notice_finance(self, **kwargs):
        return {"success": True, "payload": kwargs}


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
    register_agent_private_tools(
        registry,
        troubleshooting_tool_mode="real",
        troubleshooting_api_client=FakeTroubleshootingAPIClient(),
    )
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


async def test_endo_aftercare_mock_write_tool_result_is_returned_to_llm_when_enabled():
    registry = ToolRegistry()
    register_agent_private_tools(registry, troubleshooting_tool_mode="mock")
    llm = SequencedLLM(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_query_endo",
                        "function": {
                            "name": "query_endo_task_record",
                            "arguments": '{"apply_seq": "930123456789012"}',
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
                            "arguments": '{"apply_seq": "930123456789012", "policyNo": "9200100000458846", "endorseType": "001028"}',
                        },
                    }
                ],
                has_tool_calls=True,
                finish_reason="tool_calls",
            ),
            LLMResponse(content="已根据 mock 工具结果完成保单更新异常处理。", has_tool_calls=False),
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

    assert result.stopped_reason == "final"
    assert result.final_answer == "已根据 mock 工具结果完成保单更新异常处理。"
    assert [call["name"] for call in result.tool_calls] == ["query_endo_task_record", "notice_policy_update"]
    assert result.tool_calls[0]["result"]["mock_case"] == "policy_update_fail"
    assert result.tool_calls[1]["success"] is True
    assert result.tool_calls[1]["result"]["mock"] is True
    assert any(message.get("role") == "tool" and message.get("name") == "notice_policy_update" for message in result.messages)
