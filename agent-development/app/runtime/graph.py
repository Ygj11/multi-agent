from __future__ import annotations

"""任务级 MainGraph 定义。

本模块只编排主生命周期：会话加载、问题理解、Agent 路由、子 Agent 执行、
审批、最终验证和消息落库。业务 SOP、工具循环和真实工具执行分别下沉到
Skill、BaseSubAgent/ToolCallingRunner、ToolExecutor，避免 MainGraph 变成
所有业务逻辑的聚合点。
"""

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.card_loader import AgentCardLoader
from app.agents.dispatcher import DispatchAgentNode
from app.agents.repair_task_builder import RepairTaskBuilder
from app.agents.selection import AgentSelectionNode
from app.agents.task_assembler import AgentTaskAssembler
from app.auth.authorization_service import AuthorizationService
from app.auth.principal import principal_from_auth_context
from app.approval.service import ApprovalService
from app.config.settings import get_settings
from app.observability.logger import log_event, preview_text
from app.query.entity_resolver import build_entity_state_updates
from app.query.intent_recognition_node import IntentRecognitionNode
from app.query.query_rewrite_node import QueryRewriteNode
from app.runtime.context_builder import ContextBuilder
from app.runtime.graph_state import AgentGraphState
from app.runtime.route_policy import RoutePolicy
from app.runtime.handlers.approval_handler import ApprovalGraphHandler
from app.runtime.handlers.clarification_handler import ClarificationHandler
from app.runtime.handlers.memory_commit_handler import MemoryCommitHandler
from app.runtime.handlers.message_commit_handler import MessageCommitHandler
from app.runtime.handlers.task_completion_handler import TaskCompletionGraphHandler
from app.runtime.handlers.verification_handler import VerificationHandler
from app.schemas.agent_card import AgentCard, AgentSelectionResult
from app.schemas.entities import EntityBag
from app.schemas.enums.graph import (
    AfterApprovalCreateRoute,
    ApprovalRequiredRoute,
    ClarificationRoute,
    EntryRoute,
    GraphNode,
    TaskCompletionRoute,
    VerificationRoute,
)
from app.schemas.enums.observability import RuntimeEvent
from app.schemas.runtime import OrchestratorContext
from app.session.message_store import MessageStore
from app.session.session_manager import SessionManager
from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.subagents.manager import SubAgentManager
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.verification.service import VerificationService


class AgentGraphFactory:
    """创建 LangGraph 应用并持有节点依赖。

    AgentGraphFactory 是 graph 层的组合器，不是业务 Service。它负责把已经
    构建好的节点能力接到固定工作流上；节点内部如果需要复杂领域逻辑，应继续
    委托给 QueryRewriteNode、IntentRecognitionNode、ContextBuilder、
    DispatchAgentNode、ApprovalGraphHandler 等专门组件。
    """

    def __init__(
        self,
        *,
        session_manager: SessionManager,
        message_store: MessageStore,
        short_memory: ShortTermMemoryManager,
        query_rewrite_node: QueryRewriteNode,
        intent_recognition_node: IntentRecognitionNode,
        context_builder: ContextBuilder,
        subagent_manager: SubAgentManager,
        tool_registry: ToolRegistry,
        agent_card_loader: AgentCardLoader,
        agent_selection_node: AgentSelectionNode | None = None,
        task_assembler: AgentTaskAssembler | None = None,
        dispatch_agent_node: DispatchAgentNode | None = None,
        approval_service: ApprovalService | None = None,
        tool_executor: ToolExecutor | None = None,
        tool_calling_runner: ToolCallingRunner | None = None,
        checkpointer: Any | None = None,
        max_approval_chain_depth: int = 3,
        max_write_tools_per_request: int = 3,
        authorization_service: AuthorizationService | None = None,
        verification_service: VerificationService | None = None,
        task_completion_handler: TaskCompletionGraphHandler | None = None,
        repair_task_builder: RepairTaskBuilder | None = None,
        enable_task_completion_verify: bool = False,
    ) -> None:
        self.session_manager = session_manager
        self.message_store = message_store
        self.short_memory = short_memory
        self.query_rewrite_node = query_rewrite_node
        self.intent_recognition_node = intent_recognition_node
        self.context_builder = context_builder
        self.subagent_manager = subagent_manager
        self.tool_registry = tool_registry
        self.agent_card_loader = agent_card_loader
        self.agent_selection_node = agent_selection_node or AgentSelectionNode(agent_card_loader)
        self.task_assembler = task_assembler or AgentTaskAssembler()
        self.dispatch_agent_node = dispatch_agent_node or DispatchAgentNode(subagent_manager)
        self.approval_service = approval_service
        self.tool_executor = tool_executor
        self.tool_calling_runner = tool_calling_runner
        self.checkpointer = checkpointer or MemorySaver()
        self.max_approval_chain_depth = max_approval_chain_depth
        self.max_write_tools_per_request = max_write_tools_per_request
        self.authorization_service = authorization_service
        self.verification_service = verification_service
        self.task_completion_handler = task_completion_handler
        self.repair_task_builder = repair_task_builder or RepairTaskBuilder()
        self.enable_task_completion_verify = enable_task_completion_verify and task_completion_handler is not None
        self.log_graph_node_events = get_settings().log_graph_node_events
        self.clarification_handler = ClarificationHandler()
        self.message_commit_handler = MessageCommitHandler(message_store=message_store)
        self.memory_commit_handler = MemoryCommitHandler(short_memory=short_memory)
        self.verification_handler = VerificationHandler(verification_service=verification_service)
        self.approval_handler = ApprovalGraphHandler(
            approval_service=approval_service,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
            agent_card_loader=agent_card_loader,
            max_approval_chain_depth=max_approval_chain_depth,
            max_write_tools_per_request=max_write_tools_per_request,
        )

    def build(self):
        """构建真实 StateGraph。

        主干顺序是确定性的：先完成会话和语义理解，再做 Agent 路由和子 Agent
        执行，最后统一经过审批/验证/落库。子 Agent 内部可以让 LLM 动态选择工具，
        但外层 Graph 不把这些动态步骤摊平成节点，便于保持全局生命周期可控。
        """
        graph = StateGraph(AgentGraphState)
        graph.add_node(GraphNode.ROUTE_ENTRY.value, self.route_entry)
        graph.add_node(GraphNode.LOAD_SESSION.value, self.load_session)
        graph.add_node(GraphNode.RESUME_APPROVED_TOOL.value, self.resume_approved_tool)
        graph.add_node(GraphNode.SAVE_USER_MESSAGE.value, self.save_user_message)
        graph.add_node(GraphNode.QUERY_REWRITE.value, self.query_rewrite)
        graph.add_node(GraphNode.INTENT_RECOGNITION.value, self.intent_recognition)
        graph.add_node(GraphNode.BUILD_ORCHESTRATOR_CONTEXT.value, self.build_orchestrator_context)
        graph.add_node(GraphNode.SELECT_AGENT.value, self.select_agent)
        graph.add_node(GraphNode.DISPATCH_AGENT.value, self.dispatch_agent)
        graph.add_node(GraphNode.BUILD_CLARIFICATION_ANSWER.value, self.build_clarification_answer)
        graph.add_node(GraphNode.CHECK_HUMAN_APPROVAL_REQUIRED.value, self.check_human_approval_required)
        graph.add_node(GraphNode.COLLECT_VERIFICATION_EVIDENCE.value, self.collect_verification_evidence)
        graph.add_node(GraphNode.VERIFY_TASK_COMPLETION.value, self.verify_task_completion)
        graph.add_node(GraphNode.BUILD_REPAIR_TASK.value, self.build_repair_task)
        graph.add_node(GraphNode.DISPATCH_REPAIR_AGENT.value, self.dispatch_repair_agent)
        graph.add_node(GraphNode.BUILD_VERIFICATION_CLARIFICATION.value, self.build_verification_clarification)
        graph.add_node(GraphNode.BUILD_HANDOFF_ANSWER.value, self.build_handoff_answer)
        graph.add_node(GraphNode.CREATE_APPROVAL_REQUEST.value, self.create_approval_request)
        graph.add_node(GraphNode.SUBMIT_APPROVAL_REQUEST.value, self.submit_approval_request)
        graph.add_node(GraphNode.PAUSE_FOR_APPROVAL.value, self.pause_for_approval)
        graph.add_node(GraphNode.PRE_ANSWER_VERIFY.value, self.pre_answer_verify)
        graph.add_node(GraphNode.REGENERATE_COMPLIANT_ANSWER.value, self.regenerate_compliant_answer)
        graph.add_node(GraphNode.FALLBACK_ANSWER.value, self.fallback_answer)
        graph.add_node(GraphNode.SAVE_ASSISTANT_MESSAGE.value, self.save_assistant_message)
        graph.add_node(GraphNode.COMPRESS_SHORT_MEMORY.value, self.compress_short_memory)
        graph.add_node(GraphNode.FINALIZE_RESPONSE.value, self.finalize_response)

        graph.set_entry_point(GraphNode.ROUTE_ENTRY.value) # start节点
        graph.add_conditional_edges(
            GraphNode.ROUTE_ENTRY.value,
            self.entry_route,
            {
                EntryRoute.RESUME: GraphNode.RESUME_APPROVED_TOOL.value,
                EntryRoute.NORMAL: GraphNode.LOAD_SESSION.value,
            },
        )
        graph.add_edge(GraphNode.RESUME_APPROVED_TOOL.value, GraphNode.CHECK_HUMAN_APPROVAL_REQUIRED.value) # 有没有写工具需要审批
        graph.add_edge(GraphNode.LOAD_SESSION.value, GraphNode.SAVE_USER_MESSAGE.value)
        graph.add_edge(GraphNode.SAVE_USER_MESSAGE.value, GraphNode.QUERY_REWRITE.value)
        graph.add_conditional_edges(
            GraphNode.QUERY_REWRITE.value, # 从哪个节点开始分支
            self.clarification_route, # 用哪个函数判断路线
            {
                ClarificationRoute.CLARIFY: GraphNode.BUILD_CLARIFICATION_ANSWER.value,
                ClarificationRoute.CONTINUE: GraphNode.INTENT_RECOGNITION.value,
            },
        )
        graph.add_conditional_edges(
            GraphNode.INTENT_RECOGNITION.value,
            self.clarification_route,
            {
                ClarificationRoute.CLARIFY: GraphNode.BUILD_CLARIFICATION_ANSWER.value,
                ClarificationRoute.CONTINUE: GraphNode.BUILD_ORCHESTRATOR_CONTEXT.value,
            },
        )
        graph.add_edge(GraphNode.BUILD_ORCHESTRATOR_CONTEXT.value, GraphNode.SELECT_AGENT.value)
        graph.add_conditional_edges(
            GraphNode.SELECT_AGENT.value,
            self.clarification_route,
            {
                ClarificationRoute.CLARIFY: GraphNode.BUILD_CLARIFICATION_ANSWER.value,
                ClarificationRoute.CONTINUE: GraphNode.DISPATCH_AGENT.value,
            },
        )
        graph.add_edge(GraphNode.DISPATCH_AGENT.value, GraphNode.CHECK_HUMAN_APPROVAL_REQUIRED.value) # 有没有写工具需要审批
        graph.add_edge(GraphNode.BUILD_CLARIFICATION_ANSWER.value, GraphNode.PRE_ANSWER_VERIFY.value)
        graph.add_conditional_edges(
            GraphNode.CHECK_HUMAN_APPROVAL_REQUIRED.value,
            self.human_approval_route,
            {
                ApprovalRequiredRoute.REQUIRED: GraphNode.CREATE_APPROVAL_REQUEST.value,
                ApprovalRequiredRoute.NOT_REQUIRED: GraphNode.COLLECT_VERIFICATION_EVIDENCE.value,
                ApprovalRequiredRoute.SKIP_COMPLETION: GraphNode.PRE_ANSWER_VERIFY.value,
            },
        )
        graph.add_edge(GraphNode.COLLECT_VERIFICATION_EVIDENCE.value, GraphNode.VERIFY_TASK_COMPLETION.value)
        graph.add_conditional_edges(
            GraphNode.VERIFY_TASK_COMPLETION.value,
            self.task_completion_route,
            {
                TaskCompletionRoute.PASSED: GraphNode.PRE_ANSWER_VERIFY.value,
                TaskCompletionRoute.CONTINUE: GraphNode.BUILD_REPAIR_TASK.value,
                TaskCompletionRoute.NEED_USER: GraphNode.BUILD_VERIFICATION_CLARIFICATION.value,
                TaskCompletionRoute.HANDOFF: GraphNode.BUILD_HANDOFF_ANSWER.value,
                TaskCompletionRoute.FAILED: GraphNode.FALLBACK_ANSWER.value,
            },
        )
        graph.add_edge(GraphNode.BUILD_REPAIR_TASK.value, GraphNode.DISPATCH_REPAIR_AGENT.value)
        graph.add_edge(GraphNode.DISPATCH_REPAIR_AGENT.value, GraphNode.CHECK_HUMAN_APPROVAL_REQUIRED.value) # 有没有写工具需要审批
        graph.add_edge(GraphNode.BUILD_VERIFICATION_CLARIFICATION.value, GraphNode.PRE_ANSWER_VERIFY.value)
        graph.add_edge(GraphNode.BUILD_HANDOFF_ANSWER.value, GraphNode.PRE_ANSWER_VERIFY.value)
        graph.add_conditional_edges(
            GraphNode.CREATE_APPROVAL_REQUEST.value,
            self.after_create_approval_route,
            {
                AfterApprovalCreateRoute.SUBMIT: GraphNode.SUBMIT_APPROVAL_REQUEST.value,
                AfterApprovalCreateRoute.MANUAL: GraphNode.PRE_ANSWER_VERIFY.value,
            },
        )
        graph.add_edge(GraphNode.SUBMIT_APPROVAL_REQUEST.value, GraphNode.PAUSE_FOR_APPROVAL.value)
        graph.add_edge(GraphNode.PAUSE_FOR_APPROVAL.value, GraphNode.PRE_ANSWER_VERIFY.value)
        graph.add_conditional_edges(
            GraphNode.PRE_ANSWER_VERIFY.value,
            self.compliance_route,
            {
                VerificationRoute.PASSED: GraphNode.SAVE_ASSISTANT_MESSAGE.value,
                VerificationRoute.RETRY: GraphNode.REGENERATE_COMPLIANT_ANSWER.value,
                VerificationRoute.FALLBACK: GraphNode.FALLBACK_ANSWER.value,
            },
        )
        graph.add_edge(GraphNode.REGENERATE_COMPLIANT_ANSWER.value, GraphNode.PRE_ANSWER_VERIFY.value)
        graph.add_edge(GraphNode.FALLBACK_ANSWER.value, GraphNode.SAVE_ASSISTANT_MESSAGE.value)
        graph.add_edge(GraphNode.SAVE_ASSISTANT_MESSAGE.value, GraphNode.COMPRESS_SHORT_MEMORY.value)
        graph.add_edge(GraphNode.COMPRESS_SHORT_MEMORY.value, GraphNode.FINALIZE_RESPONSE.value)
        graph.add_edge(GraphNode.FINALIZE_RESPONSE.value, END)
        return graph.compile(checkpointer=self.checkpointer)

    async def route_entry(self, state: AgentGraphState) -> dict[str, Any]:
        return {"graph_path": self._append_path(state, GraphNode.ROUTE_ENTRY)}

    def entry_route(self, state: AgentGraphState) -> str:
        """
        route_entry 只是分流，
        真正让 state 拿到旧变量的是 ApprovalStore 里保存的 resume_state_json + pending_messages + pending_tools + pending_tool_call
        """
        return RoutePolicy.route_entry(state)

    async def load_session(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.LOAD_SESSION
        self._log_node_enter(state, node)
        session = await self.session_manager.load_session(state["session_key"])
        self._log_node_exit(state, node)
        return {
            "recent_messages": session["recent_messages"],
            "short_summary": session["short_summary"],
            "retry_count": state.get("retry_count", 0),
            "graph_path": self._append_path(state, node),
        }

    async def save_user_message(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.SAVE_USER_MESSAGE
        self._log_node_enter(state, node)
        updates = await self.message_commit_handler.save_user_message(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    async def query_rewrite(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.QUERY_REWRITE
        self._log_node_enter(state, node)
        result = await self.query_rewrite_node.rewrite(
            original_query=state["original_query"],
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
            session_key=state["session_key"],
            request_id=state.get("request_id"),
            trace_id=state.get("trace_id"),
        )
        self._log_node_exit(state, node)
        # 实体状态只能通过 build_entity_state_updates 同步写回：
        # entity_bag 是 canonical state，entities 只是由它派生的兼容视图。
        # Graph 节点不得各自用 dict merge 维护第二份实体状态。
        entity_updates = build_entity_state_updates(EntityBag(**result.entity_bag))
        return {
            "rewritten_query": result.rewritten_query,
            "rewrite_type": result.rewrite_type,
            **entity_updates,
            "conversation_window": result.conversation_window,
            "is_follow_up": result.is_follow_up,
            "need_clarification": result.need_clarification,
            "clarification_question": result.clarification_question,
            "clarification_source": "query_rewrite" if result.need_clarification else None,
            "missing_required_entities": result.missing_required_entities,
            "query_rewrite_decision_trace": result.decision_trace,
            "query_rewrite_llm_status": result.llm_status,
            "query_rewrite_fallback_reason": result.fallback_reason,
            "graph_path": self._append_path(state, node),
        }

    async def intent_recognition(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.INTENT_RECOGNITION
        self._log_node_enter(state, node)
        agent_summaries = [self._agent_card_summary(card) for card in self.agent_card_loader.list_available_agents()]
        result = await self.intent_recognition_node.recognize(
            original_query=state["original_query"],
            rewritten_query=state["rewritten_query"],
            entities=state["entities"],
            rewrite_type=state["rewrite_type"],
            conversation_window=state["conversation_window"],
            agent_card_summaries=agent_summaries,
            request_id=state.get("request_id"),
            trace_id=state.get("trace_id"),
            session_key=state.get("session_key"),
        )
        self._log_node_exit(state, node)
        # IntentRecognitionNode 只返回 intent/sub_intent 与澄清信息。
        # canonical 实体已由 query_rewrite 写入，意图识别节点不能再次修改 entity_bag。
        return {
            "intent": result.intent,
            "sub_intent": result.sub_intent,
            "confidence": result.confidence,
            "need_clarification": result.need_clarification,
            "clarification_question": result.clarification_question,
            "clarification_source": "intent_recognition" if result.need_clarification else state.get("clarification_source"),
            "intent_decision_trace": result.decision_trace,
            "intent_llm_status": result.llm_status,
            "intent_fallback_reason": result.fallback_reason,
            "graph_path": self._append_path(state, node),
        }

    async def build_orchestrator_context(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.BUILD_ORCHESTRATOR_CONTEXT
        self._log_node_enter(state, node)
        context = await self.context_builder.build_for_orchestrator(
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            intent=state.get("intent", "unknown"),
            sub_intent=state.get("sub_intent"),
            entities=state.get("entities", {}),
            entity_bag=state.get("entity_bag", {}),
            session_key=state["session_key"],
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
            auth_context=state.get("auth_context"),
        )
        self._log_node_exit(state, node)
        # OrchestratorContext 是给后续路由和子 Agent 的结构化父上下文，
        # 不是 Prompt 拼接字符串。后续节点应优先消费这里的字段，避免重复查库和重复解析。
        return {
            "orchestrator_context": context.model_dump(),
            "graph_path": self._append_path(state, node),
        }

    async def select_agent(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.SELECT_AGENT
        self._log_node_enter(state, node)
        selection = await self.agent_selection_node.select(
            intent=state.get("intent", "unknown"),
            sub_intent=state.get("sub_intent"),
            intent_confidence=state.get("confidence", 0.0),
            entities=state.get("entities", {}),
            query=state.get("rewritten_query", state["original_query"]),
            is_follow_up=bool(state.get("is_follow_up")),
            request_id=state.get("request_id"),
            trace_id=state.get("trace_id"),
            session_key=state.get("session_key"),
        )
        selected_candidate = next((item for item in selection.candidates if item.agent_name == selection.selected_agent), selection.candidates[0])
        selected_card = selected_candidate.card
        # 检查 agent 可用性，通过 agent card 的 access_policy 进行检查，配合AuthContext.Principal
        access_decision = self._check_agent_access(state, selected_card)
        if not access_decision.get("allowed", True):
            self._log_node_exit(state, node)
            return {
                "agent_selection_summary": self._agent_selection_summary(selection),
                "selected_agent": selection.selected_agent,
                "need_clarification": True,
                "clarification_question": "当前身份无权使用该业务 Agent，请联系管理员开通对应机构或岗位权限。",
                "clarification_source": "agent_authorization",
                "error": f"permission_denied:{access_decision.get('reason')}",
                "agent_selection_decision_trace": selection.decision_trace,
                "agent_selection_llm_status": selection.llm_status,
                "agent_selection_fallback_reason": selection.fallback_reason,
                "graph_path": self._append_path(state, node),
            }
        self._log_node_exit(state, node)
        return {
            "agent_selection_summary": self._agent_selection_summary(selection),
            "selected_agent": selection.selected_agent,
            "need_clarification": selection.need_clarification,
            "clarification_question": selection.clarification_question,
            "clarification_source": "agent_selection" if selection.need_clarification else state.get("clarification_source"),
            "agent_selection_decision_trace": selection.decision_trace,
            "agent_selection_llm_status": selection.llm_status,
            "agent_selection_fallback_reason": selection.fallback_reason,
            "graph_path": self._append_path(state, node),
        }

    async def dispatch_agent(self, state: AgentGraphState) -> dict[str, Any]:
        """
        dispatch_agent 执行完成，不等于“业务任务完成，SubAgentResult 可能是最终答案，也可能是“中断态结果”

        dispatch_agent
        → subagent.run()
        → ToolCallingRunner loop 第 1 次
           → LLM 调用只读工具 query_task_status
           → 工具执行成功
           → observation 回填给 LLM

        → ToolCallingRunner loop 第 2 次
           → LLM 决定调用写工具 notice_policy_update
           → ToolExecutor 判断这是写工具，需要人工审批
           → 不执行真实写工具
           → 返回 ToolResult(error="human_approval_required")

        → ToolCallingRunner 立刻停止 loop
        → 返回 ToolCallingRunResult(stopped_reason="human_approval_required")
        → BaseSubAgent 把它包装成 SubAgentResult(needs_human_approval=True)
        → dispatch_agent 节点返回
        → check_human_approval_required 检查这个 SubAgentResult
        → create_approval_request
        → pause_for_approval
        ”"""
        node = GraphNode.DISPATCH_AGENT
        self._log_node_enter(state, node)
        context = OrchestratorContext(**state["orchestrator_context"])
        selected_card = self._selected_agent_card(state)
        task = self.task_assembler.assemble(
            selected_card=selected_card,
            orchestrator_context=context,
            entities=state.get("entities", {}),
            request_id=state["request_id"],
            trace_id=state["trace_id"],
        )
        result = await self.dispatch_agent_node.dispatch(task, context)
        self._log_node_exit(state, node)
        updates: dict[str, Any] = {
            "subagent_result": result.model_dump(),
            "answer": result.answer,
            "graph_path": self._append_path(state, node),
        }
        updates.update(self._skill_pin_updates(result.model_dump(), execution_mode="initial"))
        result_metadata = result.metadata or {}
        if result_metadata.get("clarification"):
            updates.update(
                {
                    "need_clarification": True,
                    "clarification_question": result_metadata.get("clarification_question") or result.answer,
                    "clarification_source": result_metadata.get("clarification_source") or "subagent",
                    "missing_required_entities": result_metadata.get("missing_required_entities") or [],
                }
            )
        return updates

    async def resume_approved_tool(self, state: AgentGraphState) -> dict[str, Any]:
        """Resume a paused tool loop after one pending write tool was approved."""
        node = GraphNode.RESUME_APPROVED_TOOL
        self._log_node_enter(state, node)
        updates = await self.approval_handler.resume_approved_tool(state)
        subagent_result = updates.get("subagent_result") if isinstance(updates.get("subagent_result"), dict) else {}
        updates.update(self._skill_pin_updates(subagent_result, execution_mode=state.get("execution_mode") or "initial"))
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    async def check_human_approval_required(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.CHECK_HUMAN_APPROVAL_REQUIRED
        self._log_node_enter(state, node)
        updates = self.approval_handler.check_required(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    def human_approval_route(self, state: AgentGraphState) -> ApprovalRequiredRoute:
        if state.get("approval_required"):
            return ApprovalRequiredRoute.REQUIRED
        if self._should_skip_task_completion(state):
            return ApprovalRequiredRoute.SKIP_COMPLETION
        return ApprovalRequiredRoute.NOT_REQUIRED

    async def collect_verification_evidence(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.COLLECT_VERIFICATION_EVIDENCE
        if self.task_completion_handler is None:
            return {"graph_path": self._append_path(state, node)}
        self._log_node_enter(state, node)
        updates = await self.task_completion_handler.collect_verification_evidence(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    async def verify_task_completion(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.VERIFY_TASK_COMPLETION
        if self.task_completion_handler is None:
            return {"graph_path": self._append_path(state, node)}
        self._log_node_enter(state, node)
        updates = await self.task_completion_handler.verify_task_completion(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    def task_completion_route(self, state: AgentGraphState) -> str:
        return RoutePolicy.route_task_completion(state)

    async def build_repair_task(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.BUILD_REPAIR_TASK
        if self.task_completion_handler is None:
            return {"graph_path": self._append_path(state, node)}
        self._log_node_enter(state, node)
        updates = self.task_completion_handler.build_repair_task(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    async def dispatch_repair_agent(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.DISPATCH_REPAIR_AGENT
        self._log_node_enter(state, node)
        context = self._orchestrator_context_from_state(state)
        selected_card = self._selected_agent_card(state)
        task = self.repair_task_builder.build(
            selected_card=selected_card,
            orchestrator_context=context,
            state=state,
        )
        result = await self.dispatch_agent_node.dispatch(task, context)
        prior_results = list(state.get("previous_subagent_results") or [])
        if isinstance(state.get("subagent_result"), dict):
            prior_results.append(state["subagent_result"])
        updates: dict[str, Any] = {
            "subagent_result": result.model_dump(),
            "answer": result.answer,
            "previous_subagent_results": prior_results[-5:],
            "execution_mode": "repair",
            "graph_path": self._append_path(state, node),
        }
        updates.update(self._skill_pin_updates(result.model_dump(), execution_mode="repair"))
        result_metadata = result.metadata or {}
        if result_metadata.get("clarification"):
            updates.update(
                {
                    "need_clarification": True,
                    "clarification_question": result_metadata.get("clarification_question") or result.answer,
                    "clarification_source": result_metadata.get("clarification_source") or "subagent_repair",
                    "missing_required_entities": result_metadata.get("missing_required_entities") or [],
                }
            )
        self._log_node_exit(state, node)
        return updates

    async def build_verification_clarification(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.BUILD_VERIFICATION_CLARIFICATION
        if self.task_completion_handler is None:
            return {"graph_path": self._append_path(state, node)}
        self._log_node_enter(state, node)
        updates = self.task_completion_handler.build_verification_clarification(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    async def build_handoff_answer(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.BUILD_HANDOFF_ANSWER
        if self.task_completion_handler is None:
            return {"graph_path": self._append_path(state, node)}
        self._log_node_enter(state, node)
        updates = self.task_completion_handler.build_handoff_answer(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    def after_create_approval_route(self, state: AgentGraphState) -> str:
        return RoutePolicy.route_after_create_approval(state)

    async def create_approval_request(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.CREATE_APPROVAL_REQUEST
        self._log_node_enter(state, node)
        updates = await self.approval_handler.create_request(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    async def submit_approval_request(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.SUBMIT_APPROVAL_REQUEST
        self._log_node_enter(state, node)
        updates = await self.approval_handler.submit_request(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    async def pause_for_approval(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.PAUSE_FOR_APPROVAL
        self._log_node_enter(state, node)
        updates = await self.approval_handler.pause(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    async def pre_answer_verify(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.PRE_ANSWER_VERIFY
        self._log_node_enter(state, node)
        updates = await self.verification_handler.pre_answer_verify(state)
        updates["graph_path"] = self._append_path(state, node)
        self._log_node_exit(state, node)
        return updates

    def compliance_route(self, state: AgentGraphState) -> str:
        return RoutePolicy.route_verification(state)

    async def regenerate_compliant_answer(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.REGENERATE_COMPLIANT_ANSWER
        self._log_node_enter(state, node)
        safe_answer = "已完成分析，但原始回复未通过最终验证。我已改写为不暴露原始工具输出或敏感字段的安全摘要。"
        self._log_node_exit(state, node)
        return {
            "answer": safe_answer,
            "retry_count": state.get("retry_count", 0) + 1,
            "graph_path": self._append_path(state, node),
        }

    async def fallback_answer(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.FALLBACK_ANSWER
        self._log_node_enter(state, node)
        self._log_node_exit(state, node)
        return {
            "answer": "当前回复未通过最终验证，已拦截原始内容。请补充更具体的业务问题，我会在不暴露敏感信息的前提下重新说明。",
            "graph_path": self._append_path(state, node),
        }

    async def save_assistant_message(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.SAVE_ASSISTANT_MESSAGE
        self._log_node_enter(state, node)
        updates = await self.message_commit_handler.save_assistant_message(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    async def build_clarification_answer(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.BUILD_CLARIFICATION_ANSWER
        self._log_node_enter(state, node)
        updates = self.clarification_handler.build_answer(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    # 路由函数
    def clarification_route(self, state: AgentGraphState) -> str:
        return RoutePolicy.route_clarification(state)

    async def compress_short_memory(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.COMPRESS_SHORT_MEMORY
        self._log_node_enter(state, node)
        updates = await self.memory_commit_handler.compress_short_memory(state)
        self._log_node_exit(state, node)
        return {**updates, "graph_path": self._append_path(state, node)}

    async def finalize_response(self, state: AgentGraphState) -> dict[str, Any]:
        node = GraphNode.FINALIZE_RESPONSE
        self._log_node_enter(state, node)
        log_event(
            RuntimeEvent.RESPONSE_FINALIZED,
            **self._log_context(state, node),
            message="Graph response finalized",
            data={
                "intent": state.get("intent"),
                "selected_agent": state.get("selected_agent"),
                "answer_preview": preview_text(state.get("answer", "")),
            },
        )
        self._log_node_exit(state, node)
        return {"graph_path": self._append_path(state, node)}

    @staticmethod
    def _append_path(state: AgentGraphState, node: GraphNode | str) -> list[str]:
        return [*state.get("graph_path", []), str(node)]

    @staticmethod
    def _log_context(state: AgentGraphState, node: GraphNode | str) -> dict[str, Any]:
        return {
            "request_id": state.get("request_id"),
            "trace_id": state.get("trace_id"),
            "session_key": state.get("session_key"),
            "user_id": state.get("user_id"),
            "tenant_id": state.get("tenant_id"),
            "node": str(node),
        }

    def _log_node_enter(self, state: AgentGraphState, node: GraphNode | str) -> None:
        if not self._should_log_graph_node_events():
            return
        log_event(
            RuntimeEvent.LANGGRAPH_NODE_ENTER,
            **self._log_context(state, node),
            message=f"Enter LangGraph node {node}",
            data={"node": str(node)},
        )

    def _log_node_exit(self, state: AgentGraphState, node: GraphNode | str) -> None:
        if not self._should_log_graph_node_events():
            return
        log_event(
            RuntimeEvent.LANGGRAPH_NODE_EXIT,
            **self._log_context(state, node),
            message=f"Exit LangGraph node {node}",
            data={"node": str(node)},
        )

    def _check_agent_access(self, state: AgentGraphState, card: AgentCard) -> dict[str, Any]:
        if self.authorization_service is None:
            return {"allowed": True}
        principal = principal_from_auth_context(state.get("auth_context"))
        decision = self.authorization_service.check_agent_access(principal=principal, agent_card=card)
        return decision.model_dump()

    def _selected_agent_card(self, state: AgentGraphState) -> AgentCard:
        selected_agent = state.get("selected_agent")
        if not selected_agent:
            raise RuntimeError("selected_agent_required")
        card = self.agent_card_loader.get_agent_card(selected_agent)
        if card is None:
            raise RuntimeError(f"selected_agent_card_not_found:{selected_agent}")
        return card

    def _should_skip_task_completion(self, state: AgentGraphState) -> bool:
        if not self.enable_task_completion_verify:
            return True
        if state.get("need_clarification") or state.get("manual_intervention_required"):
            # 人工接管
            return True
        subagent_result = state.get("subagent_result") if isinstance(state.get("subagent_result"), dict) else {}
        metadata = subagent_result.get("metadata") if isinstance(subagent_result.get("metadata"), dict) else {}
        if metadata.get("clarification") or metadata.get("no_skill_blocked"):
            return True
        if not (state.get("selected_skill_id") or subagent_result.get("selected_skill_id")):
            return True
        return False

    @staticmethod
    def _skill_pin_updates(subagent_result: dict[str, Any], *, execution_mode: str) -> dict[str, Any]:
        selected_skill_id = subagent_result.get("selected_skill_id") if isinstance(subagent_result, dict) else None
        if not selected_skill_id:
            return {}
        updates: dict[str, Any] = {
            "selected_skill_id": selected_skill_id,
            "execution_mode": execution_mode,
        }
        if execution_mode == "initial":
            updates.update(
                {
                    "repair_round": 0,
                    "repair_history": [],
                    "last_repair_fingerprint": None,
                    "repair_no_progress_count": 0,
                    "original_subagent_result": subagent_result,
                    "previous_subagent_results": [],
                }
            )
        return updates

    @staticmethod
    def _orchestrator_context_from_state(state: AgentGraphState) -> OrchestratorContext:
        if isinstance(state.get("orchestrator_context"), dict):
            return OrchestratorContext(**state["orchestrator_context"])
        return OrchestratorContext(
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query") or state["original_query"],
            intent=state.get("intent") or "unknown",
            sub_intent=state.get("sub_intent"),
            entities=state.get("entities", {}),
            entity_bag=state.get("entity_bag", {}),
            session_key=state["session_key"],
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
            lightweight_knowledge_hints=[],
            auth_context=state.get("auth_context"),
        )

    @staticmethod
    def _agent_selection_summary(selection: AgentSelectionResult) -> dict[str, Any]:
        return {
            "selected_agent": selection.selected_agent,
            "confidence": selection.confidence,
            "selection_method": selection.selection_method, # 表达 如何选择的 rule？llm？
            "fallback_used": bool(selection.fallback_used),
            "fallback_reason": selection.fallback_reason,
            "candidate_count": len(selection.candidates),
            "llm_status": selection.llm_status,
        }

    def _should_log_graph_node_events(self) -> bool:
        return self.log_graph_node_events

    @staticmethod
    def _agent_card_summary(card: AgentCard) -> dict[str, Any]:
        return {
            "agent_name": card.agent_name,
            "description": card.description,
            "supported_routes": card.normalized_supported_routes(),
            "capabilities": card.capabilities,
            "required_entities": card.required_entities,
            "optional_entities": card.optional_entities,
            "examples": card.examples,
        }
