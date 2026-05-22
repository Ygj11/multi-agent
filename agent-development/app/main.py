from __future__ import annotations

"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.agents.card_loader import AgentCardLoader
from app.agents.dispatcher import DispatchAgentNode
from app.agents.selection import AgentSelectionNode
from app.agents.task_assembler import AgentTaskAssembler
from app.adapters.request_adapter import RequestAdapter
from app.adapters.response_adapter import ResponseAdapter
from app.compliance.final_checker import FinalComplianceChecker
from app.config.settings import get_settings
from app.knowledge.in_memory_service import InMemoryKnowledgeService
from app.llm.factory import build_llm_provider
from app.memory.long_term_memory_manager import LongTermMemoryManager
from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.mcp.capability_registry import MCPCapabilityRegistry
from app.mcp.client_manager import MCPClientManager
from app.observability.logger import log_event, preview_text
from app.query.intent_recognition_node import IntentRecognitionNode
from app.query.query_rewrite_node import QueryRewriteNode
from app.runtime.checkpoint import SQLiteCheckpointStore
from app.runtime.context_builder import ContextBuilder
from app.runtime.graph import AgentGraphFactory
from app.runtime.orchestrator import AgentOrchestrator
from app.schemas.message import ChatRequest, ChatResponse
from app.session.message_store import MessageStore
from app.session.session_manager import SessionManager
from app.storage.sqlite import SQLiteDatabase
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector
from app.subagents.claim_agent import ClaimAgent
from app.subagents.change_impact_analysis_agent import ChangeImpactAnalysisAgent
from app.subagents.compliance_security_agent import ComplianceSecurityAgent
from app.subagents.document_parse_agent import DocumentParseAgent
from app.subagents.manager import SubAgentManager
from app.subagents.policy_query_agent import PolicyQueryAgent
from app.subagents.troubleshooting_agent import TroubleshootingAgent
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.audit_store import ToolCallLogStore, ToolExecutionLogStore
from app.tools.agent_tools import register_agent_private_tools
from app.tools.http_tools import HTTPRequestTool, MCPHTTPCallTool
from app.tools.executor import ToolExecutor
from app.tools.public_tools import register_public_tools
from app.tools.registry import ToolRegistry
from app.tools.shell_exec_tool import ShellExecTool


def create_app(sqlite_db_path: str | Path | None = None) -> FastAPI:
    """创建应用并组装第二阶段 SQLite 持久化 MVP 所需依赖。"""
    settings = get_settings()
    db = SQLiteDatabase(sqlite_db_path or settings.sqlite_db_path)
    message_store = MessageStore(db=db)
    short_memory = ShortTermMemoryManager(db=db)
    checkpoint_store = SQLiteCheckpointStore(db=db)
    tool_call_log_store = ToolCallLogStore(db=db)
    tool_execution_log_store = ToolExecutionLogStore(db=db)
    _long_memory = LongTermMemoryManager()
    llm_provider = build_llm_provider(settings)
    knowledge_service = InMemoryKnowledgeService()
    mcp_capability_registry = MCPCapabilityRegistry()
    mcp_client_manager = MCPClientManager(settings=settings, capability_registry=mcp_capability_registry)

    session_manager = SessionManager(message_store=message_store, short_memory=short_memory)
    tool_registry = ToolRegistry()
    register_public_tools(tool_registry, knowledge_service)
    register_agent_private_tools(tool_registry)
    # Keep restricted operational tools registered but unavailable unless a card explicitly opts in.
    tool_registry.register_private(
        agent_name="admin_agent",
        name="shell_exec",
        tool=ShellExecTool(project_root=settings.project_root),
        is_write=False,
    )
    tool_registry.register_private(
        agent_name="admin_agent",
        name="http_request",
        tool=HTTPRequestTool(timeout=settings.http_tool_timeout),
    )
    tool_registry.register_private(
        agent_name="admin_agent",
        name="mcp_http.call_tool",
        tool=MCPHTTPCallTool(timeout=settings.http_tool_timeout),
    )
    tool_executor = ToolExecutor(
        registry=tool_registry,
        log_store=tool_execution_log_store,
        mcp_client_manager=mcp_client_manager,
    )
    tool_calling_runner = ToolCallingRunner(llm_provider=llm_provider, tool_executor=tool_executor)
    skills_root = Path(__file__).resolve().parent / "skills"
    skill_catalog = SkillCatalog(skills_root=skills_root)
    context_builder = ContextBuilder(
        skills_root=skills_root,
        knowledge_service=knowledge_service,
        skill_catalog=skill_catalog,
        skill_selector=SkillSelector(),
    )

    subagent_manager = SubAgentManager(skill_catalog=skill_catalog)
    subagent_manager.register(
        "troubleshooting_agent",
        TroubleshootingAgent(
            context_builder=context_builder,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
        ),
    )
    subagent_manager.register(
        "compliance_agent",
        ComplianceSecurityAgent(
            context_builder=context_builder,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
        ),
    )
    subagent_manager.register(
        "document_parse_agent",
        DocumentParseAgent(context_builder=context_builder, tool_executor=tool_executor),
    )
    subagent_manager.register(
        "change_impact_analysis_agent",
        ChangeImpactAnalysisAgent(context_builder=context_builder, tool_executor=tool_executor),
    )
    subagent_manager.register(
        "policy_query_agent",
        PolicyQueryAgent(
            context_builder=context_builder,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
        ),
    )
    subagent_manager.register(
        "claim_agent",
        ClaimAgent(
            context_builder=context_builder,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
        ),
    )

    cards_root = Path(__file__).resolve().parent / "agents" / "cards"
    agent_card_loader = AgentCardLoader(cards_root=cards_root)
    agent_card_loader.validate_with_skill_catalog(skill_catalog)

    graph = AgentGraphFactory(
        session_manager=session_manager,
        message_store=message_store,
        short_memory=short_memory,
        query_rewrite_node=QueryRewriteNode(llm_provider=llm_provider),
        intent_recognition_node=IntentRecognitionNode(llm_provider=llm_provider),
        context_builder=context_builder,
        subagent_manager=subagent_manager,
        tool_registry=tool_registry,
        agent_card_loader=agent_card_loader,
        agent_selection_node=AgentSelectionNode(agent_card_loader, llm_provider=llm_provider),
        task_assembler=AgentTaskAssembler(),
        dispatch_agent_node=DispatchAgentNode(subagent_manager),
        final_compliance_checker=FinalComplianceChecker(llm_provider=llm_provider),
    ).build()
    orchestrator = AgentOrchestrator(graph, checkpoint_store=checkpoint_store)

    request_adapter = RequestAdapter()
    response_adapter = ResponseAdapter()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Discover MCP tools at startup without blocking service availability."""
        if settings.enable_mcp_client:
            await mcp_client_manager.initialize()
            tool_registry.register_mcp_tools(mcp_capability_registry.list_tools())
            log_event(
                "mcp_capabilities_registered",
                node="app_startup",
                message="MCP capabilities registered into ToolRegistry",
                data={
                    "tool_count": len(mcp_capability_registry.list_tools()),
                    "servers": [status.model_dump() for status in mcp_client_manager.get_server_statuses()],
                },
            )
        yield

    app = FastAPI(title="Health Insurance Agent MVP", lifespan=lifespan)
    app.state.message_store = message_store
    app.state.short_memory = short_memory
    app.state.checkpoint_store = checkpoint_store
    app.state.legacy_tool_call_log_store = tool_call_log_store
    app.state.tool_call_log_store = tool_execution_log_store
    app.state.tool_execution_log_store = tool_execution_log_store
    app.state.knowledge_service = knowledge_service
    app.state.mcp_client_manager = mcp_client_manager
    app.state.mcp_capability_registry = mcp_capability_registry
    app.state.skill_catalog = skill_catalog
    app.state.agent_card_loader = agent_card_loader
    app.state.tool_registry = tool_registry
    app.state.tool_executor = tool_executor
    app.state.llm_provider = llm_provider
    app.state.tool_calling_runner = tool_calling_runner
    app.state.sqlite_db = db
    app.state.orchestrator = orchestrator

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        """聊天接口：请求适配 -> LangGraph 执行 -> 响应适配。"""
        log_event(
            "request_received",
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            node="api_chat",
            message="Chat request received",
            data={
                "channel": request.channel,
                "session_id": request.session_id,
                "message_count": len(request.messages),
                "last_message_preview": preview_text(request.messages[-1].content if request.messages else ""),
            },
        )
        try:
            inbound = request_adapter.adapt(request)
            state = await orchestrator.run(inbound)
            response = response_adapter.adapt(state)
            log_event(
                "response_returned",
                request_id=response.request_id,
                trace_id=state.get("trace_id"),
                session_key=response.session_key,
                user_id=state.get("user_id"),
                tenant_id=state.get("tenant_id"),
                node="api_chat",
                message="Chat response returned",
                data={"intent": response.intent, "answer_preview": preview_text(response.answer)},
            )
            return response
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()
