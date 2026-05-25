from pathlib import Path

from app.knowledge.in_memory_service import InMemoryKnowledgeService
from app.llm.schemas import LLMResponse
from app.mcp.schemas import MCPToolCapability
from app.runtime.context_builder import ContextBuilder
from app.schemas.agent_card import AgentCard
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector
from app.subagents.troubleshooting_agent import TroubleshootingAgent
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from tests.fakes.mcp import FakeMCPClientManager


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, "kwargs": kwargs})
        if len(self.calls) == 1:
            return LLMResponse(
                content=None,
                has_tool_calls=True,
                tool_calls=[{"name": "mcp.workflow.query_refund_task", "arguments": {"policy_no": "9201344266"}}],
            )
        return LLMResponse(content="MCP refund task checked.", has_tool_calls=False)


def _card():
    return AgentCard(
        agent_name="troubleshooting_agent",
        display_name="Troubleshooting",
        description="test",
        capabilities=["test"],
        supported_intents=["troubleshooting"],
        required_entities=[],
        output_schema="SubAgentResult",
        private_tools=[],
        public_tools_allowed=False,
        mcp_tools=["mcp.workflow.query_refund_task"],
        mcp_tool_scopes=[],
        skills=["troubleshooting_agent.refund_failure"],
        rag_namespaces=[],
        enabled=True,
        version="1",
    )


async def test_subagent_loop_can_call_authorized_mcp_tool():
    registry = ToolRegistry()
    registry.register_mcp_tools(
        [
            MCPToolCapability(
                server_name="workflow",
                original_tool_name="query_refund_task",
                registered_tool_name="mcp.workflow.query_refund_task",
                description="query refund task",
                input_schema={"type": "object", "properties": {"policy_no": {"type": "string"}}},
            )
        ]
    )
    llm = FakeLLM()
    mcp_manager = FakeMCPClientManager()
    executor = ToolExecutor(registry=registry, mcp_client_manager=mcp_manager)
    runner = ToolCallingRunner(llm_provider=llm, tool_executor=executor)
    skills_root = Path("app/skills")
    context_builder = ContextBuilder(
        skills_root=skills_root,
        knowledge_service=InMemoryKnowledgeService(),
        skill_catalog=SkillCatalog(skills_root),
        skill_selector=SkillSelector(),
    )
    agent = TroubleshootingAgent(context_builder=context_builder, tool_executor=executor, tool_calling_runner=runner)
    card = _card()
    task = SubAgentTask(
        name="troubleshooting_agent",
        query="保单9201344266为什么退保没有成功",
        intent="troubleshooting",
        session_key="s-agent-mcp",
        original_query="保单9201344266为什么退保没有成功",
        entities={"policy_no": "9201344266"},
        task_id="task-1",
        metadata={"request_id": "req-1", "agent_card": card.model_dump()},
    )
    parent_context = OrchestratorContext(
        original_query=task.original_query,
        rewritten_query=task.query,
        intent=task.intent,
        entities=task.entities,
        session_key=task.session_key,
        recent_messages=[],
        short_summary=None,
        available_subagents=["troubleshooting_agent"],
        available_tools=[],
        lightweight_knowledge_hints=[],
    )

    result = await agent.run(task, parent_context)

    first_tools = {tool["function"]["name"] for tool in llm.calls[0]["tools"]}
    assert "mcp.workflow.query_refund_task" in first_tools
    assert mcp_manager.calls == [("mcp.workflow.query_refund_task", {"policy_no": "9201344266"})]
    assert any(message["role"] == "tool" for message in llm.calls[1]["messages"])
    assert result.answer == "MCP refund task checked."
    assert result.tool_calls[0]["name"] == "mcp.workflow.query_refund_task"
