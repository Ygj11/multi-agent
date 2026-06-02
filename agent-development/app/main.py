from __future__ import annotations

"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException

from app.approval.client import ApprovalSystemClient
from app.approval.service import ApprovalService
from app.auth.authorization_service import AuthorizationService, ResourceAccessService
from app.auth.dependencies import get_current_principal
from app.auth.principal import Principal
from app.agents.card_loader import AgentCardLoader
from app.agents.dispatcher import DispatchAgentNode
from app.agents.selection import AgentSelectionNode
from app.agents.task_assembler import AgentTaskAssembler
from app.adapters.request_adapter import RequestAdapter
from app.adapters.response_adapter import ResponseAdapter
from app.bootstrap.agents import build_subagent_manager
from app.bootstrap.storage import build_storage
from app.bootstrap.tools import register_admin_restricted_tools
from app.bootstrap.verification import build_verification_service
from app.config.settings import get_settings
from app.knowledge.factory import build_knowledge_service
from app.llm.factory import build_llm_provider
from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.mcp.capability_registry import MCPCapabilityRegistry
from app.mcp.client_manager import MCPClientManager
from app.observability.logger import log_event, preview_text
from app.query.intent_recognition_node import IntentRecognitionNode
from app.query.query_rewrite_node import QueryRewriteNode
from app.runtime.checkpoint import build_checkpointer
from app.runtime.context_builder import ContextBuilder
from app.runtime.graph import AgentGraphFactory
from app.runtime.orchestrator import AgentOrchestrator
from app.schemas.approval import ApprovalCallbackRequest, ApprovalCallbackResponse
from app.schemas.message import ChatRequest, ChatResponse
from app.session.session_manager import SessionManager
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.agent_tools import register_agent_private_tools
from app.tools.executor import ToolExecutor
from app.tools.public_tools import register_public_tools
from app.tools.registry import ToolRegistry


def create_app(sqlite_db_path: str | Path | None = None) -> FastAPI:
    """创建应用"""
    settings = get_settings()
    storage = build_storage(settings, sqlite_db_path)
    db = storage.db
    message_store = storage.message_store
    llm_provider = build_llm_provider(settings)
    short_memory = ShortTermMemoryManager(db=db, llm_provider=llm_provider)
    checkpoint_store = storage.checkpoint_store
    langgraph_checkpointer = build_checkpointer(settings)
    tool_execution_log_store = storage.tool_execution_log_store
    evidence_store = storage.evidence_store
    approval_store = storage.approval_store
    knowledge_service = build_knowledge_service(settings)
    mcp_capability_registry = MCPCapabilityRegistry()
    mcp_client_manager = MCPClientManager(settings=settings, capability_registry=mcp_capability_registry)

    session_manager = SessionManager(message_store=message_store, short_memory=short_memory)
    tool_registry = ToolRegistry()
    authorization_service = AuthorizationService()
    resource_access_service = ResourceAccessService()
    register_public_tools(tool_registry, knowledge_service)
    register_agent_private_tools(tool_registry)
    register_admin_restricted_tools(tool_registry, settings)
    verification_service = build_verification_service(llm_provider)
    tool_executor = ToolExecutor(
        registry=tool_registry,
        log_store=tool_execution_log_store,
        mcp_client_manager=mcp_client_manager,
        approval_store=approval_store,
        write_idempotency_enabled=settings.tool_write_idempotency_enabled,
        authorization_service=authorization_service,
        resource_access_service=resource_access_service,
        verification_service=verification_service,
        evidence_store=evidence_store,
    )
    tool_calling_runner = ToolCallingRunner(
        llm_provider=llm_provider,
        tool_executor=tool_executor,
        max_iterations=settings.tool_loop_max_iterations,
        max_consecutive_tool_failures=settings.tool_loop_max_consecutive_failures,
        max_same_tool_failures=settings.tool_loop_max_same_tool_failures,
        max_duplicate_tool_calls=settings.tool_loop_max_duplicate_calls,
    )
    approval_service = ApprovalService(
        store=approval_store,
        client=ApprovalSystemClient(settings=settings),
        verification_service=verification_service,
        message_store=message_store,
        short_memory=short_memory,
        callback_url=settings.approval_callback_url,
    )
    skills_root = Path(__file__).resolve().parent / "skills"
    skill_catalog = SkillCatalog(skills_root=skills_root)
    context_builder = ContextBuilder(
        skills_root=skills_root,
        knowledge_service=knowledge_service,
        skill_catalog=skill_catalog,
        skill_selector=SkillSelector(
            llm_provider=llm_provider,
            enable_llm_rerank=settings.enable_skill_llm_rerank,
            top_k=settings.skill_llm_rerank_top_k,
            min_margin=settings.skill_llm_rerank_min_margin,
        ),
    )

    subagent_manager = build_subagent_manager(
        skill_catalog=skill_catalog,
        context_builder=context_builder,
        tool_executor=tool_executor,
        tool_calling_runner=tool_calling_runner,
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
        approval_service=approval_service,
        tool_executor=tool_executor,
        tool_calling_runner=tool_calling_runner,
        checkpointer=langgraph_checkpointer,
        max_approval_chain_depth=settings.max_approval_chain_depth,
        max_write_tools_per_request=settings.max_write_tools_per_request,
        authorization_service=authorization_service,
        verification_service=verification_service,
    ).build()
    orchestrator = AgentOrchestrator(graph, checkpoint_store=checkpoint_store)
    approval_service.orchestrator = orchestrator

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
    app.state.langgraph_checkpointer = langgraph_checkpointer
    app.state.tool_execution_log_store = tool_execution_log_store
    app.state.evidence_store = evidence_store
    app.state.approval_store = approval_store
    app.state.approval_service = approval_service
    app.state.knowledge_service = knowledge_service
    app.state.mcp_client_manager = mcp_client_manager
    app.state.mcp_capability_registry = mcp_capability_registry
    app.state.skill_catalog = skill_catalog
    app.state.agent_card_loader = agent_card_loader
    app.state.tool_registry = tool_registry
    app.state.tool_executor = tool_executor
    app.state.authorization_service = authorization_service
    app.state.resource_access_service = resource_access_service
    app.state.verification_service = verification_service
    app.state.llm_provider = llm_provider
    app.state.tool_calling_runner = tool_calling_runner
    app.state.sqlite_db = db
    app.state.orchestrator = orchestrator

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest, principal: Principal | None = Depends(get_current_principal)) -> ChatResponse:
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
            inbound = request_adapter.adapt(request, principal=principal)
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
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/approval/callback", response_model=ApprovalCallbackResponse)
    async def approval_callback(request: ApprovalCallbackRequest) -> ApprovalCallbackResponse:
        """Receive external approval decisions and resume the paused flow."""
        try:
            result = await approval_service.handle_callback(request)
            return ApprovalCallbackResponse(
                approval_id=result.approval_request.approval_id,
                status=result.approval_request.status,
                resumed=result.resumed,
                final_answer=result.final_answer,
                error=result.error,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"approval not found: {request.approval_id}") from exc

    @app.get("/api/approval/{approval_id}")
    async def get_approval(approval_id: str) -> dict:
        """Return the current approval result for frontend polling."""
        item = await approval_store.get(approval_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"approval not found: {approval_id}")
        return {
            "approval_id": item.approval_id,
            "status": item.status,
            "final_answer": item.final_answer,
            "error": item.error,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "decided_at": item.decided_at,
        }

    return app


app = create_app()
