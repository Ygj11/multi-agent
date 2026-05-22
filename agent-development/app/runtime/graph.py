from __future__ import annotations

"""LangGraph StateGraph definition for the task-level orchestrator."""

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.card_loader import AgentCardLoader
from app.agents.dispatcher import DispatchAgentNode
from app.agents.selection import AgentSelectionNode
from app.agents.task_assembler import AgentTaskAssembler
from app.compliance.final_checker import FinalComplianceChecker
from app.observability.logger import log_event, preview_text
from app.query.intent_recognition_node import IntentRecognitionNode
from app.query.query_rewrite_node import QueryRewriteNode
from app.runtime.context_builder import ContextBuilder
from app.runtime.graph_state import AgentGraphState
from app.schemas.agent_card import AgentCard, AgentSelectionResult
from app.schemas.agent_task import AgentTaskEnvelope
from app.schemas.compliance import FinalComplianceResult
from app.schemas.runtime import OrchestratorContext
from app.session.message_store import MessageStore
from app.session.session_manager import SessionManager
from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.subagents.manager import SubAgentManager
from app.tools.registry import ToolRegistry


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
        final_compliance_checker: FinalComplianceChecker | None = None,
        checkpointer: MemorySaver | None = None,
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
        self.final_compliance_checker = final_compliance_checker or FinalComplianceChecker()
        self.checkpointer = checkpointer or MemorySaver()

    def build(self):
        """Build the real StateGraph with task-level orchestration nodes."""
        graph = StateGraph(AgentGraphState)
        graph.add_node("load_session", self.load_session)
        graph.add_node("save_user_message", self.save_user_message)
        graph.add_node("query_rewrite", self.query_rewrite)
        graph.add_node("intent_recognition", self.intent_recognition)
        graph.add_node("build_orchestrator_context", self.build_orchestrator_context)
        graph.add_node("discover_agents", self.discover_agents)
        graph.add_node("select_agent", self.select_agent)
        graph.add_node("assemble_task", self.assemble_task)
        graph.add_node("dispatch_agent", self.dispatch_agent)
        graph.add_node("final_compliance_check", self.final_compliance_check)
        graph.add_node("regenerate_compliant_answer", self.regenerate_compliant_answer)
        graph.add_node("fallback_answer", self.fallback_answer)
        graph.add_node("save_assistant_message", self.save_assistant_message)
        graph.add_node("compress_short_memory", self.compress_short_memory)
        graph.add_node("finalize_response", self.finalize_response)

        graph.set_entry_point("load_session")
        graph.add_edge("load_session", "save_user_message")
        graph.add_edge("save_user_message", "query_rewrite")
        graph.add_edge("query_rewrite", "intent_recognition")
        graph.add_edge("intent_recognition", "build_orchestrator_context")
        graph.add_edge("build_orchestrator_context", "discover_agents")
        graph.add_edge("discover_agents", "select_agent")
        graph.add_edge("select_agent", "assemble_task")
        graph.add_edge("assemble_task", "dispatch_agent")
        graph.add_edge("dispatch_agent", "final_compliance_check")
        graph.add_conditional_edges(
            "final_compliance_check",
            self.compliance_route,
            {
                "passed": "save_assistant_message",
                "retry": "regenerate_compliant_answer",
                "fallback": "fallback_answer",
            },
        )
        graph.add_edge("regenerate_compliant_answer", "final_compliance_check")
        graph.add_edge("fallback_answer", "save_assistant_message")
        graph.add_edge("save_assistant_message", "compress_short_memory")
        graph.add_edge("compress_short_memory", "finalize_response")
        graph.add_edge("finalize_response", END)
        return graph.compile(checkpointer=self.checkpointer)

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
        await self.message_store.append(
            session_key=state["session_key"],
            role="user",
            content=state["original_query"],
            metadata={
                "request_id": state["request_id"],
                "trace_id": state["trace_id"],
                "original_query": state["original_query"],
                "session_key": state["session_key"],
            },
        )
        self._log_node_exit(state, "save_user_message")
        return {"graph_path": self._append_path(state, "save_user_message")}

    async def query_rewrite(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "query_rewrite")
        result = await self.query_rewrite_node.rewrite(
            original_query=state["original_query"],
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
        )
        self._log_node_exit(state, "query_rewrite")
        return {
            "rewritten_query": result.rewritten_query,
            "graph_path": self._append_path(state, "query_rewrite"),
        }

    async def intent_recognition(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "intent_recognition")
        result = await self.intent_recognition_node.recognize(
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
        )
        self._log_node_exit(state, "intent_recognition")
        return {
            "intent": result.intent,
            "confidence": result.confidence,
            "entities": result.entities,
            "target_subagent": None,
            "required_tools": [],
            "graph_path": self._append_path(state, "intent_recognition"),
        }

    async def build_orchestrator_context(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "build_orchestrator_context")
        context = await self.context_builder.build_for_orchestrator(
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            intent=state.get("intent", "unknown"),
            entities=state.get("entities", {}),
            session_key=state["session_key"],
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
            available_subagents=self.subagent_manager.list_agents(),
            available_tools=self.tool_registry.list_tools(),
        )
        self._log_node_exit(state, "build_orchestrator_context")
        return {
            "orchestrator_context": context.model_dump(),
            "graph_path": self._append_path(state, "build_orchestrator_context"),
        }

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
            entities=state.get("entities", {}),
            query=state.get("rewritten_query", state["original_query"]),
            request_id=state.get("request_id"),
            trace_id=state.get("trace_id"),
            session_key=state.get("session_key"),
        )
        selected_card = selection.candidates[0].card
        self._log_node_exit(state, "select_agent")
        return {
            "agent_selection": selection.model_dump(),
            "selected_agent": selection.selected_agent,
            "selected_agent_card": selected_card.model_dump(),
            "graph_path": self._append_path(state, "select_agent"),
        }

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
        return {
            "subagent_result": result.model_dump(),
            "answer": result.answer,
            "selected_skill_id": result.selected_skill_id,
            "selected_skill_metadata": result.selected_skill_metadata,
            "skill_selection_score": result.skill_selection_score,
            "skill_selection_reason": result.skill_selection_reason,
            "graph_path": self._append_path(state, "dispatch_agent"),
        }

    async def final_compliance_check(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "final_compliance_check")
        result = await self.final_compliance_checker.check(state.get("answer", ""))
        updates: dict[str, Any] = {
            "final_compliance_result": result.model_dump(),
            "graph_path": self._append_path(state, "final_compliance_check"),
        }
        if result.passed:
            updates["answer"] = result.sanitized_answer
        self._log_node_exit(state, "final_compliance_check")
        return updates

    def compliance_route(self, state: AgentGraphState) -> str:
        result = FinalComplianceResult(**state["final_compliance_result"])
        if result.passed:
            return "passed"
        if result.retry_required and state.get("retry_count", 0) < 1:
            return "retry"
        return "fallback"

    async def regenerate_compliant_answer(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "regenerate_compliant_answer")
        result = FinalComplianceResult(**state["final_compliance_result"])
        safe_answer = (
            "已完成分析，但原始回复包含内部字段或敏感内容。"
            f"脱敏摘要：{result.sanitized_answer}"
        )
        self._log_node_exit(state, "regenerate_compliant_answer")
        return {
            "answer": safe_answer,
            "retry_count": state.get("retry_count", 0) + 1,
            "graph_path": self._append_path(state, "regenerate_compliant_answer"),
        }

    async def fallback_answer(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "fallback_answer")
        result = FinalComplianceResult(**state["final_compliance_result"])
        self._log_node_exit(state, "fallback_answer")
        return {
            "answer": result.fallback_answer,
            "graph_path": self._append_path(state, "fallback_answer"),
        }

    async def save_assistant_message(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "save_assistant_message")
        await self.message_store.append(
            session_key=state["session_key"],
            role="assistant",
            content=state.get("answer", ""),
            metadata={
                "request_id": state["request_id"],
                "trace_id": state["trace_id"],
                "original_query": state["original_query"],
                "rewritten_query": state.get("rewritten_query"),
                "intent": state.get("intent"),
                "entities": state.get("entities", {}),
                "selected_agent": state.get("selected_agent"),
                "session_key": state["session_key"],
            },
        )
        self._log_node_exit(state, "save_assistant_message")
        return {"graph_path": self._append_path(state, "save_assistant_message")}

    async def compress_short_memory(self, state: AgentGraphState) -> dict[str, Any]:
        self._log_node_enter(state, "compress_short_memory")
        summary = await self.short_memory.compress_after_turn(
            session_key=state["session_key"],
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            intent=state.get("intent", "unknown"),
            answer=state.get("answer", ""),
            subagent_result=state.get("subagent_result"),
        )
        self._log_node_exit(state, "compress_short_memory")
        return {"short_summary": summary, "graph_path": self._append_path(state, "compress_short_memory")}

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
