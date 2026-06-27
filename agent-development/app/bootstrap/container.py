from __future__ import annotations

"""运行时应用容器装配。

Container 是 Agent runtime 的组合根：负责构建具体对象，并管理进程级
startup/shutdown 生命周期。内部业务组件仍然接收显式依赖，不能依赖整个
container，避免退化成 Service Locator。
"""

import asyncio
from dataclasses import dataclass, field
import inspect
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
from app.config.settings import Settings, assert_settings_valid, validate_settings
from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.integrations.clients import IntegrationClients
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
from app.runtime.handlers.task_completion_handler import TaskCompletionGraphHandler
from app.runtime.orchestrator import AgentOrchestrator
from app.runtime.session_locks import SessionExecutionLockManager
from app.session.session_manager import SessionManager
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector
from app.subagents.manager import SubAgentManager
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.agent_tools import register_agent_private_tools
from app.tools.executor import ToolExecutor
from app.tools.public_tools import register_public_tools
from app.tools.registry import ToolRegistry
from app.verification.task_completion.evidence_collector import VerificationEvidenceCollector
from app.verification.task_completion.service import TaskCompletionVerifierService
from app.verification.task_completion.state_probes.endo_aftercare import EndoCompletionAftercareProbe


@dataclass(slots=True)
class AppContainer:
    """顶层运行时依赖容器与生命周期边界。

    每个 FastAPI/Uvicorn worker 应拥有自己的 AppContainer 和连接池。
    关闭后不支持原地重启；需要重新 build 一个新的 container。
    """

    settings: Settings
    storage: StorageBundle
    llm_provider: Any
    short_memory: ShortTermMemoryManager
    langgraph_checkpointer: Any
    knowledge_service: Any
    integration_clients: IntegrationClients
    mcp_capability_registry: MCPCapabilityRegistry
    mcp_client_manager: MCPClientManager
    intent_taxonomy_loader: IntentTaxonomyLoader
    session_manager: SessionManager
    tool_registry: ToolRegistry
    authorization_service: AuthorizationService
    resource_access_service: ResourceAccessService
    verification_service: Any
    task_completion_verifier_service: TaskCompletionVerifierService
    task_completion_evidence_collector: VerificationEvidenceCollector
    task_completion_handler: TaskCompletionGraphHandler
    tool_executor: ToolExecutor
    tool_calling_runner: ToolCallingRunner
    approval_service: ApprovalService
    skill_catalog: SkillCatalog
    context_builder: ContextBuilder
    subagent_manager: SubAgentManager
    agent_card_loader: AgentCardLoader
    graph: Any
    session_locks: SessionExecutionLockManager
    orchestrator: AgentOrchestrator
    _started: bool = False
    _closed: bool = False
    _lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @property
    def started(self) -> bool:
        """Whether process-level async resources have completed startup."""
        return self._started

    @property
    def closed(self) -> bool:
        """Container 是否已经永久结束生命周期。关闭后应新建 Container，而非原地重启。"""
        return self._closed

    async def startup(self) -> None:
        """Initialize enabled external resources and dynamic capabilities once."""
        async with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("AppContainer is closed; build a new container before startup")
            if self._started:
                return
            try:
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
            except Exception:
                await self._shutdown_resources()
                self._closed = True
                raise
            self._started = True

    async def shutdown(self) -> None:
        """释放进程级 HTTP 连接池与 MCP client，关闭失败不阻断其余资源。"""
        async with self._lifecycle_lock:
            if self._closed:
                return
            await self._shutdown_resources()
            self._started = False
            self._closed = True

    async def _shutdown_resources(self) -> None:
        """按依赖逆序释放已构造资源，可被 startup 半失败路径复用。"""
        await self._close_resource("tool_registry", self.tool_registry)
        await self._close_resource("approval_system_client", self.approval_service.client)
        await self._close_resource("mcp_client_manager", self.mcp_client_manager, method_name="shutdown")
        await self._close_resource("troubleshooting_api_client", self.integration_clients.troubleshooting)
        await self._close_resource("pos_api_client", self.integration_clients.pos)
        await self._close_resource("knowledge_service", self.knowledge_service)
        await self._close_resource("llm_provider", self.llm_provider)

    @staticmethod
    async def _close_resource(name: str, resource: Any, *, method_name: str = "close") -> None:
        """兼容可选依赖和异步关闭方法，单个失败只记录告警。"""
        if resource is None:
            return
        close = getattr(resource, method_name, None)
        if not callable(close):
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            log_event(
                "runtime_resource_close_failed",
                level="WARNING",
                node="app_shutdown",
                message="Runtime resource close failed",
                data={"resource": name, "error": str(exc)},
            )


def build_app_container(settings: Settings, sqlite_db_path: str | Path | None = None) -> AppContainer:
    """同步构建 Agent runtime。

    这里允许本地确定性初始化：加载 YAML/Skill/AgentCard、构建 SQLite store、
    注册本地工具、装配 Graph。需要网络或 await 的 MCP 能力发现放在 startup。
    """
    assert_settings_valid(settings)
    _log_config_warnings(settings)
    validate_real_tool_configuration(settings)
    storage = build_storage(settings, sqlite_db_path)
    db = storage.db
    llm_provider = build_llm_provider(settings)
    short_memory = ShortTermMemoryManager(db=db, llm_provider=llm_provider)
    langgraph_checkpointer = build_checkpointer(settings)
    knowledge_service = build_knowledge_service(settings)
    integration_clients = _build_integration_clients(settings)
    mcp_capability_registry = MCPCapabilityRegistry()
    mcp_client_manager = MCPClientManager(settings=settings, capability_registry=mcp_capability_registry)
    intent_taxonomy_loader = IntentTaxonomyLoader()
    intent_taxonomy = intent_taxonomy_loader.load()

    session_manager = SessionManager(message_store=storage.message_store, short_memory=short_memory)
    tool_registry = ToolRegistry()
    authorization_service = AuthorizationService()
    resource_access_service = ResourceAccessService()

    # 注册工具只建立运行时 ToolDefinition 与可见性关系，不执行任何外部工具。
    register_public_tools(tool_registry, knowledge_service)
    register_agent_private_tools(
        tool_registry,
        integration_clients=integration_clients,
        pos_tool_mode=settings.pos_tool_mode,
        troubleshooting_tool_mode=settings.troubleshooting_tool_mode,
    )
    register_admin_restricted_tools(tool_registry, settings)

    # contract 校验属于启动期治理：prod 环境严格失败，非 prod 只记录告警。
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

    # 启动期静态校验三者关系：taxonomy 定义合法意图，AgentCard 声明覆盖范围，
    # Skill 声明自身服务的 intent/sub_intent 与私有工具。
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

    task_completion_evidence_collector = VerificationEvidenceCollector(
        skill_catalog=skill_catalog,
        evidence_store=storage.evidence_store,
        probes=[EndoCompletionAftercareProbe()],
        enable_state_probes=settings.task_completion_enable_state_probes,
    )
    task_completion_verifier_service = TaskCompletionVerifierService(
        skill_catalog=skill_catalog,
        llm_provider=llm_provider,
        enable_llm=settings.task_completion_enable_llm,
        min_confidence=settings.task_completion_min_verifier_confidence,
        fail_closed=settings.task_completion_fail_closed,
    )
    task_completion_handler = TaskCompletionGraphHandler(
        evidence_collector=task_completion_evidence_collector,
        verifier_service=task_completion_verifier_service,
        max_repair_rounds=settings.task_completion_max_repair_rounds,
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
        task_completion_handler=task_completion_handler,
        enable_task_completion_verify=settings.enable_task_completion_verify,
    ).build()

    session_locks = SessionExecutionLockManager(
        enabled=settings.enable_session_execution_lock,
        timeout_seconds=settings.session_lock_timeout_seconds,
    )
    orchestrator = AgentOrchestrator(
        graph,
        checkpoint_store=storage.checkpoint_store,
        session_locks=session_locks,
    )
    approval_service.orchestrator = orchestrator

    return AppContainer(
        settings=settings,
        storage=storage,
        llm_provider=llm_provider,
        short_memory=short_memory,
        langgraph_checkpointer=langgraph_checkpointer,
        knowledge_service=knowledge_service,
        integration_clients=integration_clients,
        mcp_capability_registry=mcp_capability_registry,
        mcp_client_manager=mcp_client_manager,
        intent_taxonomy_loader=intent_taxonomy_loader,
        session_manager=session_manager,
        tool_registry=tool_registry,
        authorization_service=authorization_service,
        resource_access_service=resource_access_service,
        verification_service=verification_service,
        task_completion_verifier_service=task_completion_verifier_service,
        task_completion_evidence_collector=task_completion_evidence_collector,
        task_completion_handler=task_completion_handler,
        tool_executor=tool_executor,
        tool_calling_runner=tool_calling_runner,
        approval_service=approval_service,
        skill_catalog=skill_catalog,
        context_builder=context_builder,
        subagent_manager=subagent_manager,
        agent_card_loader=agent_card_loader,
        graph=graph,
        session_locks=session_locks,
        orchestrator=orchestrator,
    )


def validate_real_tool_configuration(settings: Settings) -> None:
    """Fail fast when real tool modes lack required upstream configuration."""
    if settings.pos_tool_mode == "real" and not settings.pos_api_base_url:
        raise ValueError("POS_TOOL_MODE=real requires POS_API_BASE_URL.")
    if settings.troubleshooting_tool_mode == "real" and not settings.troubleshooting_api_base_url:
        raise ValueError("TROUBLESHOOTING_TOOL_MODE=real requires TROUBLESHOOTING_API_BASE_URL.")


def _build_integration_clients(settings: Settings) -> IntegrationClients:
    """按工具模式构建真实领域 client，并作为只读集合注入运行时。"""
    pos = None
    if settings.pos_tool_mode == "real":
        pos = PosAPIClient(
            BaseIntegrationHTTPClient(
                base_url=settings.pos_api_base_url,
                timeout=settings.pos_api_timeout,
            )
        )

    troubleshooting = None
    if settings.troubleshooting_tool_mode == "real":
        troubleshooting = TroubleshootingAPIClient(
            BaseIntegrationHTTPClient(
                base_url=settings.troubleshooting_api_base_url,
                timeout=settings.troubleshooting_api_timeout,
            )
        )
    return IntegrationClients(pos=pos, troubleshooting=troubleshooting)


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


def _log_config_warnings(settings: Settings) -> None:
    """记录非阻断配置治理提示；error 已由 assert_settings_valid 拦截。"""
    warnings = [issue for issue in validate_settings(settings) if issue.level == "warning"]
    if not warnings:
        return
    log_event(
        "runtime_config_validation_warning",
        level="WARNING",
        node="app_startup",
        message="Runtime configuration produced warnings",
        data={
            "warnings": [
                {
                    "code": issue.code,
                    "variables": list(issue.variables),
                    "message": issue.message,
                }
                for issue in warnings
            ]
        },
    )
