from __future__ import annotations

"""Runtime application container bootstrap.

The container is the composition root for the Agent runtime. It builds concrete
runtime objects and owns process-level startup/shutdown boundaries, while inner
components still receive explicit dependencies instead of the whole container.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.approval.client import ApprovalSystemClient
from app.approval.service import ApprovalService
from app.auth.authorization_service import AuthorizationService, ResourceAccessService
from app.agents.card_loader import AgentCardLoader
from app.agents.dispatcher import DispatchAgentNode
from app.agents.selection import AgentSelectionNode
from app.agents.task_assembler import AgentTaskAssembler
from app.bootstrap.agents import build_subagent_manager
from app.bootstrap.storage import StorageBundle, build_storage
from app.bootstrap.tools import register_admin_restricted_tools
from app.bootstrap.verification import build_verification_service
from app.config.settings import Settings
from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.integrations.pos_api_client import PosAPIClient
from app.integrations.troubleshooting_api_client import TroubleshootingAPIClient
from app.knowledge.factory import build_knowledge_service
from app.llm.factory import build_llm_provider
from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.mcp.capability_registry import MCPCapabilityRegistry
from app.mcp.client_manager import MCPClientManager
from app.observability.logger import log_event
from app.query.intent_recognition_node import IntentRecognitionNode
from app.query.intent_taxonomy_loader import IntentTaxonomyLoader
from app.query.query_rewrite_node import QueryRewriteNode
from app.runtime.checkpoint import build_checkpointer
from app.runtime.context_builder import ContextBuilder
from app.runtime.graph import AgentGraphFactory
from app.runtime.orchestrator import AgentOrchestrator
from app.session.session_manager import SessionManager
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector
from app.subagents.manager import SubAgentManager
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.agent_tools import register_agent_private_tools
from app.tools.executor import ToolExecutor
from app.tools.public_tools import register_public_tools
from app.tools.registry import ToolRegistry


@dataclass(slots=True)
class AppContainer:
    """Top-level runtime dependency container and lifecycle boundary."""

    settings: Settings
    storage: StorageBundle
    llm_provider: Any
    short_memory: ShortTermMemoryManager
    langgraph_checkpointer: Any
    knowledge_service: Any
    pos_api_client: PosAPIClient | None
    troubleshooting_api_client: TroubleshootingAPIClient | None
    mcp_capability_registry: MCPCapabilityRegistry
    mcp_client_manager: MCPClientManager
    intent_taxonomy_loader: IntentTaxonomyLoader
    session_manager: SessionManager
    tool_registry: ToolRegistry
    authorization_service: AuthorizationService
    resource_access_service: ResourceAccessService
    verification_service: Any
    tool_executor: ToolExecutor
    tool_calling_runner: ToolCallingRunner
    approval_service: ApprovalService
    skill_catalog: SkillCatalog
    context_builder: ContextBuilder
    subagent_manager: SubAgentManager
    agent_card_loader: AgentCardLoader
    graph: Any
    orchestrator: AgentOrchestrator
    _started: bool = False

    @property
    def started(self) -> bool:
        """Whether process-level async resources have completed startup."""
        return self._started

    async def startup(self) -> None:
        """Initialize enabled external resources and dynamic capabilities once."""
        if self._started:
            return
        if self.settings.enable_mcp_client:
            await self.mcp_client_manager.initialize()
            self.tool_registry.register_mcp_tools(self.mcp_capability_registry.list_tools())
            contract_errors = self.tool_registry.validate_contracts(strict=self.settings.app_env == "prod")
            log_event(
                "mcp_capabilities_registered",
                node="app_startup",
                message="MCP capabilities registered into ToolRegistry",
                data={
                    "tool_count": len(self.mcp_capability_registry.list_tools()),
                    "servers": [status.model_dump() for status in self.mcp_client_manager.get_server_statuses()],
                    "contract_errors": contract_errors,
                },
            )
        self._started = True

    async def shutdown(self) -> None:
        """Release process-level async resources when supported.

        Current MCP clients do not expose a close/shutdown protocol, so this is a
        lifecycle boundary and state reset for now.
        """
        if not self._started:
            return
        self._started = False


def build_app_container(settings: Settings, sqlite_db_path: str | Path | None = None) -> AppContainer:
    """Build the Agent runtime with deterministic local initialization."""
    validate_real_tool_configuration(settings)
    storage = build_storage(settings, sqlite_db_path)
    db = storage.db
    llm_provider = build_llm_provider(settings)
    short_memory = ShortTermMemoryManager(db=db, llm_provider=llm_provider)
    langgraph_checkpointer = build_checkpointer(settings)
    knowledge_service = build_knowledge_service(settings)
    pos_api_client = _build_pos_api_client(settings)
    troubleshooting_api_client = _build_troubleshooting_api_client(settings)
    mcp_capability_registry = MCPCapabilityRegistry()
    mcp_client_manager = MCPClientManager(settings=settings, capability_registry=mcp_capability_registry)
    intent_taxonomy_loader = IntentTaxonomyLoader()
    intent_taxonomy = intent_taxonomy_loader.load()

    session_manager = SessionManager(message_store=storage.message_store, short_memory=short_memory)
    tool_registry = ToolRegistry()
    authorization_service = AuthorizationService()
    resource_access_service = ResourceAccessService()
    register_public_tools(tool_registry, knowledge_service)
    register_agent_private_tools(
        tool_registry,
        pos_api_client=pos_api_client,
        pos_tool_mode=settings.pos_tool_mode,
        troubleshooting_tool_mode=settings.troubleshooting_tool_mode,
        troubleshooting_api_client=troubleshooting_api_client,
    )
    register_admin_restricted_tools(tool_registry, settings)
    _log_contract_warnings(tool_registry, settings)

    verification_service = build_verification_service(llm_provider)
    tool_executor = ToolExecutor(
        registry=tool_registry,
        log_store=storage.tool_execution_log_store,
        mcp_client_manager=mcp_client_manager,
        approval_store=storage.approval_store,
        write_idempotency_enabled=settings.tool_write_idempotency_enabled,
        authorization_service=authorization_service,
        resource_access_service=resource_access_service,
        verification_service=verification_service,
        evidence_store=storage.evidence_store,
        unknown_mcp_tool_policy=settings.unknown_mcp_tool_policy,
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
        store=storage.approval_store,
        client=ApprovalSystemClient(settings=settings),
        verification_service=verification_service,
        message_store=storage.message_store,
        short_memory=short_memory,
        callback_url=settings.approval_callback_url,
    )

    app_root = Path(__file__).resolve().parents[1]
    skills_root = app_root / "skills"
    skill_catalog = SkillCatalog(skills_root=skills_root)
    cards_root = app_root / "agents" / "cards"
    agent_card_loader = AgentCardLoader(cards_root=cards_root)
    agent_card_loader.validate_with_intent_taxonomy(
        intent_taxonomy,
        require_full_coverage=settings.strict_taxonomy_route_coverage,
    )
    skill_catalog.validate_with_intent_taxonomy(intent_taxonomy)
    agent_card_loader.validate_with_skill_catalog(skill_catalog)
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
        no_skill_policy=settings.no_skill_policy,
        app_env=settings.app_env,
    )
    subagent_manager = build_subagent_manager(
        skill_catalog=skill_catalog,
        context_builder=context_builder,
        agent_card_loader=agent_card_loader,
        tool_executor=tool_executor,
        tool_calling_runner=tool_calling_runner,
    )

    graph = AgentGraphFactory(
        session_manager=session_manager,
        message_store=storage.message_store,
        short_memory=short_memory,
        query_rewrite_node=QueryRewriteNode(llm_provider=llm_provider),
        intent_recognition_node=IntentRecognitionNode(llm_provider=llm_provider, intent_taxonomy_loader=intent_taxonomy_loader),
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
    orchestrator = AgentOrchestrator(graph, checkpoint_store=storage.checkpoint_store)
    approval_service.orchestrator = orchestrator

    return AppContainer(
        settings=settings,
        storage=storage,
        llm_provider=llm_provider,
        short_memory=short_memory,
        langgraph_checkpointer=langgraph_checkpointer,
        knowledge_service=knowledge_service,
        pos_api_client=pos_api_client,
        troubleshooting_api_client=troubleshooting_api_client,
        mcp_capability_registry=mcp_capability_registry,
        mcp_client_manager=mcp_client_manager,
        intent_taxonomy_loader=intent_taxonomy_loader,
        session_manager=session_manager,
        tool_registry=tool_registry,
        authorization_service=authorization_service,
        resource_access_service=resource_access_service,
        verification_service=verification_service,
        tool_executor=tool_executor,
        tool_calling_runner=tool_calling_runner,
        approval_service=approval_service,
        skill_catalog=skill_catalog,
        context_builder=context_builder,
        subagent_manager=subagent_manager,
        agent_card_loader=agent_card_loader,
        graph=graph,
        orchestrator=orchestrator,
    )


def validate_real_tool_configuration(settings: Settings) -> None:
    """Fail fast when real tool modes lack required upstream configuration."""
    if settings.pos_tool_mode == "real" and not settings.pos_api_base_url:
        raise ValueError("POS_TOOL_MODE=real requires POS_API_BASE_URL.")
    if settings.troubleshooting_tool_mode == "real" and not settings.troubleshooting_api_base_url:
        raise ValueError("TROUBLESHOOTING_TOOL_MODE=real requires TROUBLESHOOTING_API_BASE_URL.")


def _build_pos_api_client(settings: Settings) -> PosAPIClient | None:
    """仅在 POS real 模式构造真实领域 Client。"""
    if settings.pos_tool_mode != "real":
        return None
    return PosAPIClient(
        BaseIntegrationHTTPClient(
            base_url=settings.pos_api_base_url,
            timeout=settings.pos_api_timeout,
        )
    )


def _build_troubleshooting_api_client(settings: Settings) -> TroubleshootingAPIClient | None:
    """仅在 troubleshooting real 模式构造真实领域 Client。"""
    if settings.troubleshooting_tool_mode != "real":
        return None
    return TroubleshootingAPIClient(
        BaseIntegrationHTTPClient(
            base_url=settings.troubleshooting_api_base_url,
            timeout=settings.troubleshooting_api_timeout,
        )
    )


def _log_contract_warnings(tool_registry: ToolRegistry, settings: Settings) -> None:
    contract_errors = tool_registry.validate_contracts(strict=settings.app_env == "prod")
    if contract_errors:
        log_event(
            "tool_contract_validation_warning",
            level="WARNING",
            node="app_startup",
            message="Tool contract validation produced warnings",
            data={"errors": contract_errors},
        )
