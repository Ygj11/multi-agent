from __future__ import annotations

"""LangGraph StateGraph definition for the task-level orchestrator."""

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.card_loader import AgentCardLoader
from app.agents.dispatcher import DispatchAgentNode
from app.agents.selection import AgentSelectionNode
from app.agents.task_assembler import AgentTaskAssembler
from app.auth.authorization_service import AuthorizationService
from app.auth.principal import principal_from_auth_context
from app.approval.service import ApprovalService
from app.observability.logger import log_event, preview_text
from app.query.intent_recognition_node import IntentRecognitionNode
from app.query.query_rewrite_node import QueryRewriteNode
from app.runtime.context_builder import ContextBuilder
from app.runtime.graph_state import AgentGraphState
from app.runtime.handlers.approval_handler import ApprovalGraphHandler
from app.runtime.handlers.clarification_handler import ClarificationHandler
from app.runtime.handlers.memory_commit_handler import MemoryCommitHandler
from app.runtime.handlers.message_commit_handler import MessageCommitHandler
from app.runtime.handlers.verification_handler import VerificationHandler
from app.schemas.agent_card import AgentCard, AgentSelectionResult
from app.schemas.agent_task import AgentTaskEnvelope
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
    """Creates the LangGraph application and owns node dependencies."""

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
        self.clarification_handler = ClarificationHandler()
        self.message_commit_handler = MessageCommitHandler(message_store=message_store)
        self.memory_commit_handler = MemoryCommitHandler(short_memory=short_memory)
        self.verification_handler = VerificationHandler(verification_service=verification_service)
        self.approval_handler = ApprovalGraphHandler(
            approval_service=approval_service,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
            max_approval_chain_depth=max_approval_chain_depth,
            max_write_tools_per_request=max_write_tools_per_request,
        )

    def build(self):
        """Build the real StateGraph with task-level orchestration nodes."""
        graph = StateGraph(AgentGraphState)
        graph.add_node("route_entry", self.route_entry)
        graph.add_node("load_session", self.load_session)
        graph.add_node("resume_approved_tool", self.resume_approved_tool)
        graph.add_node("save_user_message", self.save_user_message)
        graph.add_node("query_rewrite", self.query_rewrite)
        graph.add_node("intent_recognition", self.intent_recognition)
        graph.add_node("build_orchestrator_context", self.build_orchestrator_context)
        graph.add_node("discover_agents", self.discover_agents)
        graph.add_node("select_agent", self.select_agent)
        graph.add_node("assemble_task", self.assemble_task)
        graph.add_node("dispatch_agent", self.dispatch_agent)
        graph.add_node("build_clarification_answer", self.build_clarification_answer)
        graph.add_node("check_human_approval_required", self.check_human_approval_required)
        graph.add_node("create_approval_request", self.create_approval_request)
        graph.add_node("submit_approval_request", self.submit_approval_request)
        graph.add_node("pause_for_approval", self.pause_for_approval)
        graph.add_node("pre_answer_verify", self.pre_answer_verify)
        graph.add_node("regenerate_compliant_answer", self.regenerate_compliant_answer)
        graph.add_node("fallback_answer", self.fallback_answer)
        graph.add_node("save_assistant_message", self.save_assistant_message)
        graph.add_node("compress_short_memory", self.compress_short_memory)
        graph.add_node("finalize_response", self.finalize_response)

        graph.set_entry_point("route_entry")
        graph.add_conditional_edges(
            "route_entry",
            self.entry_route,
            {"resume": "resume_approved_tool", "normal": "load_session"},
        )
        graph.add_edge("resume_approved_tool", "check_human_approval_required")
        graph.add_edge("load_session", "save_user_message")
        graph.add_edge("save_user_message", "query_rewrite")
        graph.add_conditional_edges(
            "query_rewrite",
            self.clarification_route,
            {"clarify": "build_clarification_answer", "continue": "intent_recognition"},
        )
        graph.add_conditional_edges(
            "intent_recognition",
            self.clarification_route,
            {"clarify": "build_clarification_answer", "continue": "build_orchestrator_context"},
        )
        graph.add_edge("build_orchestrator_context", "discover_agents")
        graph.add_edge("discover_agents", "select_agent")
        graph.add_conditional_edges(
            "select_agent",
            self.clarification_route,
            {"clarify": "build_clarification_answer", "continue": "assemble_task"},
        )
        graph.add_edge("assemble_task", "dispatch_agent")
        graph.add_edge("dispatch_agent", "check_human_approval_required")
        graph.add_edge("build_clarification_answer", "pre_answer_verify")
        graph.add_conditional_edges(
            "check_human_approval_required",
            self.human_approval_route,
            {
                "required": "create_approval_request",
                "not_required": "pre_answer_verify",
            },
        )
        graph.add_conditional_edges(
            "create_approval_request",
            self.after_create_approval_route,
            {"submit": "submit_approval_request", "manual": "pre_answer_verify"},
        )
        graph.add_edge("submit_approval_request", "pause_for_approval")
        graph.add_edge("pause_for_approval", "pre_answer_verify")
        graph.add_conditional_edges(
            "pre_answer_verify",
            self.compliance_route,
            {
                "passed": "save_assistant_message",
                "retry": "regenerate_compliant_answer",
                "fallback": "fallback_answer",
            },
        )
        graph.add_edge("regenerate_compliant_answer", "pre_answer_verify")
        graph.add_edge("fallback_answer", "save_assistant_message")
        graph.add_edge("save_assistant_message", "compress_short_memory")
        graph.add_edge("compress_short_memory", "finalize_response")
        graph.add_edge("finalize_response", END)
        return graph.compile(checkpointer=self.checkpointer)

    async def route_entry(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "route_entry")
        self._log_node_exit(state, "route_entry")
        return {"graph_path": self._append_path(state, "route_entry")}

    def entry_route(self, state: AgentGraphState) -> str:
        return "resume" if state.get("approval_resume") else "normal"

    async def load_session(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "load_session")
        session = await self.session_manager.load_session(state["session_key"])
        self._log_node_exit(state, "load_session")
        return {
            "recent_messages": session["recent_messages"],
            "short_summary": session["short_summary"],
            "retry_count": state.get("retry_count", 0),
            "graph_path": self._append_path(state, "load_session"),
        }

    async def save_user_message(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "save_user_message")
        updates = await self.message_commit_handler.save_user_message(state)
        self._log_node_exit(state, "save_user_message")
        return {**updates, "graph_path": self._append_path(state, "save_user_message")}

    async def query_rewrite(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "query_rewrite")
        result = await self.query_rewrite_node.rewrite(
            original_query=state["original_query"],
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
            session_key=state["session_key"],
        )
        self._log_node_exit(state, "query_rewrite")
        return {
            "rewritten_query": result.rewritten_query,
            "entities": result.entities,
            "entity_bag": result.entity_bag,
            "conversation_window": result.conversation_window,
            "is_follow_up": result.is_follow_up,
            "need_clarification": result.need_clarification,
            "clarification_question": result.clarification_question,
            "clarification_source": "query_rewrite" if result.need_clarification else None,
            "missing_required_entities": result.missing_required_entities,
            "graph_path": self._append_path(state, "query_rewrite"),
        }

    async def intent_recognition(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "intent_recognition")
        agent_summaries = [self._agent_card_summary(card) for card in self.agent_card_loader.list_available_agents()]
        result = await self.intent_recognition_node.recognize(
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
            current_entities=state.get("entities", {}),
            conversation_window=state.get("conversation_window", {}),
            agent_card_summaries=agent_summaries,
        )
        self._log_node_exit(state, "intent_recognition")
        merged_entities = {**(state.get("entities") or {}), **(result.entities or {})}
        return {
            "intent": result.intent,
            "sub_intent": result.sub_intent,
            "confidence": result.confidence,
            "entities": merged_entities,
            "need_clarification": result.need_clarification,
            "clarification_question": result.clarification_question,
            "clarification_source": "intent_recognition" if result.need_clarification else state.get("clarification_source"),
            "missing_required_entities": result.missing_required_entities,
            "graph_path": self._append_path(state, "intent_recognition"),
        }

    async def build_orchestrator_context(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "build_orchestrator_context")
        context = await self.context_builder.build_for_orchestrator(
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            intent=state.get("intent", "unknown"),
            sub_intent=state.get("sub_intent"),
            entities=state.get("entities", {}),
            entity_bag=state.get("entity_bag", {}),
            conversation_window=state.get("conversation_window", {}),
            session_key=state["session_key"],
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
            available_subagents=self.subagent_manager.list_agents(),
            auth_context=state.get("auth_context"),
        )
        self._log_node_exit(state, "build_orchestrator_context")
        return {
            "orchestrator_context": context.model_dump(),
            "graph_path": self._append_path(state, "build_orchestrator_context"),
        }

    """
        1. 从 AgentCardLoader 里拿 enabled 的 AgentCard 对象
        2. 转成 dict/json 可序列化结构
        3. 写入 graph state 的 available_agents
    """
    async def discover_agents(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "discover_agents")
        cards = self.agent_card_loader.list_available_agents()
        payload = [card.model_dump() for card in cards]
        self._log_node_exit(state, "discover_agents")
        return {
            "available_agents": payload,
            "graph_path": self._append_path(state, "discover_agents"),
        }

    async def select_agent(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "select_agent")
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
        access_decision = self._check_agent_access(state, selected_card)
        if not access_decision.get("allowed", True):
            self._log_node_exit(state, "select_agent")
            return {
                "agent_selection": selection.model_dump(),
                "selected_agent": selection.selected_agent,
                "selected_agent_card": selected_card.model_dump(),
                "need_clarification": True,
                "clarification_question": "当前身份无权使用该业务 Agent，请联系管理员开通对应机构或岗位权限。",
                "clarification_source": "agent_authorization",
                "error": f"permission_denied:{access_decision.get('reason')}",
                "graph_path": self._append_path(state, "select_agent"),
            }
        self._log_node_exit(state, "select_agent")
        return {
            "agent_selection": selection.model_dump(),
            "selected_agent": selection.selected_agent,
            "selected_agent_card": selected_card.model_dump(),
            "need_clarification": selection.need_clarification,
            "clarification_question": selection.clarification_question,
            "clarification_source": "agent_selection" if selection.need_clarification else state.get("clarification_source"),
            "graph_path": self._append_path(state, "select_agent"),
        }

    """参数组装层，只是组装时会做一点 memory 裁剪"""
    async def assemble_task(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "assemble_task")
        context = OrchestratorContext(**state["orchestrator_context"])
        card = AgentCard(**state["selected_agent_card"])
        task = self.task_assembler.assemble(
            selected_card=card,
            orchestrator_context=context,
            entities=state.get("entities", {}),
            request_id=state["request_id"],
            trace_id=state["trace_id"],
        )
        self._log_node_exit(state, "assemble_task")
        return {
            "assembled_task": task.model_dump(),
            "graph_path": self._append_path(state, "assemble_task"),
        }

    async def dispatch_agent(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "dispatch_agent")
        context = OrchestratorContext(**state["orchestrator_context"])
        task = AgentTaskEnvelope(**state["assembled_task"])
        result = await self.dispatch_agent_node.dispatch(task, context)
        self._log_node_exit(state, "dispatch_agent")
        updates: dict[str, Any] = {
            "subagent_result": result.model_dump(),
            "answer": result.answer,
            "graph_path": self._append_path(state, "dispatch_agent"),
        }
        result_metadata = result.metadata or {}
        if result_metadata.get("clarification"):
            updates.update(
                {
                    "need_clarification": True,
                    "clarification_question": result_metadata.get("clarification_question") or result.answer,
                    "clarification_source": result_metadata.get("clarification_source") or "subagent",
                    "missing_required_entities": result_metadata.get("missing_required_entities") or [],
                    "entities": result_metadata.get("entities") or state.get("entities", {}),
                }
            )
        return updates

    async def resume_approved_tool(self, state: AgentGraphState) -> dict[str, Any]:
        """Resume a paused tool loop after one pending write tool was approved."""
        self._log_node_enter(state, "resume_approved_tool")
        updates = await self.approval_handler.resume_approved_tool(state)
        self._log_node_exit(state, "resume_approved_tool")
        return {**updates, "graph_path": self._append_path(state, "resume_approved_tool")}

    async def check_human_approval_required(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "check_human_approval_required")
        updates = self.approval_handler.check_required(state)
        self._log_node_exit(state, "check_human_approval_required")
        return {**updates, "graph_path": self._append_path(state, "check_human_approval_required")}

    def human_approval_route(self, state: AgentGraphState) -> str:
        return ApprovalGraphHandler.human_route(state)

    def after_create_approval_route(self, state: AgentGraphState) -> str:
        return ApprovalGraphHandler.after_create_route(state)

    async def create_approval_request(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "create_approval_request")
        updates = await self.approval_handler.create_request(state)
        self._log_node_exit(state, "create_approval_request")
        return {**updates, "graph_path": self._append_path(state, "create_approval_request")}

    async def submit_approval_request(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "submit_approval_request")
        updates = await self.approval_handler.submit_request(state)
        self._log_node_exit(state, "submit_approval_request")
        return {**updates, "graph_path": self._append_path(state, "submit_approval_request")}

    async def pause_for_approval(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "pause_for_approval")
        updates = await self.approval_handler.pause(state)
        self._log_node_exit(state, "pause_for_approval")
        return {**updates, "graph_path": self._append_path(state, "pause_for_approval")}

    async def pre_answer_verify(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "pre_answer_verify")
        updates = await self.verification_handler.pre_answer_verify(state)
        updates["graph_path"] = self._append_path(state, "pre_answer_verify")
        self._log_node_exit(state, "pre_answer_verify")
        return updates

    def compliance_route(self, state: AgentGraphState) -> str:
        return VerificationHandler.route(state)

    async def regenerate_compliant_answer(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "regenerate_compliant_answer")
        safe_answer = "已完成分析，但原始回复未通过最终验证。我已改写为不暴露原始工具输出或敏感字段的安全摘要。"
        self._log_node_exit(state, "regenerate_compliant_answer")
        return {
            "answer": safe_answer,
            "retry_count": state.get("retry_count", 0) + 1,
            "graph_path": self._append_path(state, "regenerate_compliant_answer"),
        }

    async def fallback_answer(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "fallback_answer")
        self._log_node_exit(state, "fallback_answer")
        return {
            "answer": "当前回复未通过最终验证，已拦截原始内容。请补充更具体的业务问题，我会在不暴露敏感信息的前提下重新说明。",
            "graph_path": self._append_path(state, "fallback_answer"),
        }

    async def save_assistant_message(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "save_assistant_message")
        updates = await self.message_commit_handler.save_assistant_message(state)
        self._log_node_exit(state, "save_assistant_message")
        return {**updates, "graph_path": self._append_path(state, "save_assistant_message")}

    async def build_clarification_answer(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "build_clarification_answer")
        updates = self.clarification_handler.build_answer(state)
        self._log_node_exit(state, "build_clarification_answer")
        return {**updates, "graph_path": self._append_path(state, "build_clarification_answer")}

    # 路由函数
    def clarification_route(self, state: AgentGraphState) -> str:
        return "clarify" if state.get("need_clarification") else "continue"

    async def compress_short_memory(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "compress_short_memory")
        updates = await self.memory_commit_handler.compress_short_memory(state)
        self._log_node_exit(state, "compress_short_memory")
        return {**updates, "graph_path": self._append_path(state, "compress_short_memory")}

    async def finalize_response(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "finalize_response")
        log_event(
            "response_finalized",
            **self._log_context(state, "finalize_response"),
            message="Graph response finalized",
            data={
                "intent": state.get("intent"),
                "selected_agent": state.get("selected_agent"),
                "answer_preview": preview_text(state.get("answer", "")),
            },
        )
        self._log_node_exit(state, "finalize_response")
        return {"graph_path": self._append_path(state, "finalize_response")}

    @staticmethod
    def _append_path(state: AgentGraphState, node: str) -> list[str]:
        return [*state.get("graph_path", []), node]

    @staticmethod
    def _log_context(state: AgentGraphState, node: str) -> dict[str, Any]:
        return {
            "request_id": state.get("request_id"),
            "trace_id": state.get("trace_id"),
            "session_key": state.get("session_key"),
            "user_id": state.get("user_id"),
            "tenant_id": state.get("tenant_id"),
            "node": node,
        }

    def _log_node_enter(self, state: AgentGraphState, node: str) -> None:
        log_event(
            "langgraph_node_enter",
            **self._log_context(state, node),
            message=f"Enter LangGraph node {node}",
            data={"node": node},
        )

    def _log_node_exit(self, state: AgentGraphState, node: str) -> None:
        log_event(
            "langgraph_node_exit",
            **self._log_context(state, node),
            message=f"Exit LangGraph node {node}",
            data={"node": node},
        )

    def _check_agent_access(self, state: AgentGraphState, card: AgentCard) -> dict[str, Any]:
        if self.authorization_service is None:
            return {"allowed": True}
        principal = principal_from_auth_context(state.get("auth_context"))
        decision = self.authorization_service.check_agent_access(principal=principal, agent_card=card)
        return decision.model_dump()

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
