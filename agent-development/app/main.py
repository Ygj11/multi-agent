from __future__ import annotations

"""FastAPI 应用入口。"""

from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.adapters.request_adapter import RequestAdapter
from app.adapters.response_adapter import ResponseAdapter
from app.config.settings import get_settings
from app.knowledge.in_memory_service import InMemoryKnowledgeService
from app.llm.fake_provider import FakeLLMProvider
from app.memory.long_term_memory_manager import LongTermMemoryManager
from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.mcp.fake_connector import FakeMCPConnector
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
from app.subagents.change_impact_analysis_agent import ChangeImpactAnalysisAgent
from app.subagents.compliance_security_agent import ComplianceSecurityAgent
from app.subagents.document_parse_agent import DocumentParseAgent
from app.subagents.manager import SubAgentManager
from app.subagents.troubleshooting_agent import TroubleshootingAgent
from app.tools.broker import ToolBroker
from app.tools.audit_store import ToolCallLogStore
from app.tools.builtin_tools import build_get_knowledge_tool, query_internal_log
from app.tools.http_tools import HTTPRequestTool, MCPHTTPCallTool
from app.tools.mcp_tools import build_mcp_tool
from app.tools.policy_gate import PolicyGate
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
    _long_memory = LongTermMemoryManager()
    _llm = FakeLLMProvider()
    knowledge_service = InMemoryKnowledgeService()
    mcp_connector = FakeMCPConnector()

    session_manager = SessionManager(message_store=message_store, short_memory=short_memory)
    tool_registry = ToolRegistry()
    # 注册内部工具、受限 shell_exec，以及通过 wrapper 暴露的 fake MCP 工具。
    tool_registry.register("get_knowledge", build_get_knowledge_tool(knowledge_service))
    tool_registry.register("query_internal_log", query_internal_log)
    tool_registry.register(
        "partner_trace.get_request_detail",
        build_mcp_tool(mcp_connector, "partner_trace.get_request_detail"),
    )
    tool_registry.register("shell_exec", ShellExecTool(project_root=settings.project_root))
    # HTTP 类工具默认由 PolicyGate 拒绝，只有显式开启并命中 host 白名单才会执行。
    tool_registry.register("http_request", HTTPRequestTool(timeout=settings.http_tool_timeout))
    tool_registry.register("mcp_http.call_tool", MCPHTTPCallTool(timeout=settings.http_tool_timeout))

    policy_gate = PolicyGate(settings=settings)
    tool_broker = ToolBroker(
        registry=tool_registry,
        policy_gate=policy_gate,
        audit_store=tool_call_log_store,
    )
    skills_root = Path(__file__).resolve().parent / "skills"
    skill_catalog = SkillCatalog(skills_root=skills_root)
    context_builder = ContextBuilder(
        skills_root=skills_root,
        knowledge_service=knowledge_service,
        skill_catalog=skill_catalog,
        skill_selector=SkillSelector(),
    )

    subagent_manager = SubAgentManager(skill_catalog=skill_catalog)
    # 固定 Agent Catalog：只有显式注册的子 Agent 才能被 LangGraph 路由调用。
    subagent_manager.register(
        "troubleshooting_agent",
        TroubleshootingAgent(context_builder=context_builder, tool_broker=tool_broker),
    )
    subagent_manager.register(
        "compliance_security_agent",
        ComplianceSecurityAgent(context_builder=context_builder, tool_broker=tool_broker),
    )
    subagent_manager.register(
        "document_parse_agent",
        DocumentParseAgent(context_builder=context_builder, tool_broker=tool_broker),
    )
    subagent_manager.register(
        "change_impact_analysis_agent",
        ChangeImpactAnalysisAgent(context_builder=context_builder, tool_broker=tool_broker),
    )

    graph = AgentGraphFactory(
        session_manager=session_manager,
        message_store=message_store,
        short_memory=short_memory,
        query_rewrite_node=QueryRewriteNode(),
        intent_recognition_node=IntentRecognitionNode(),
        context_builder=context_builder,
        subagent_manager=subagent_manager,
        tool_registry=tool_registry,
    ).build()
    orchestrator = AgentOrchestrator(graph, checkpoint_store=checkpoint_store)

    request_adapter = RequestAdapter()
    response_adapter = ResponseAdapter()

    app = FastAPI(title="Health Insurance Agent MVP")
    app.state.message_store = message_store
    app.state.short_memory = short_memory
    app.state.checkpoint_store = checkpoint_store
    app.state.tool_call_log_store = tool_call_log_store
    app.state.knowledge_service = knowledge_service
    app.state.mcp_connector = mcp_connector
    app.state.skill_catalog = skill_catalog
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
