from __future__ import annotations

"""LangGraph 状态机定义。

本文件是 MVP 的核心编排层，所有固定节点和条件路由都在这里声明。
"""

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.observability.logger import log_event, preview_text
from app.query.intent_recognition_node import IntentRecognitionNode
from app.query.query_rewrite_node import QueryRewriteNode
from app.runtime.context_builder import ContextBuilder
from app.runtime.graph_state import AgentGraphState
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask
from app.session.message_store import MessageStore
from app.session.session_manager import SessionManager
from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.subagents.manager import SubAgentManager
from app.tools.registry import ToolRegistry


class AgentGraphFactory:
    """创建并持有 LangGraph 节点依赖。"""

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
        checkpointer: MemorySaver | None = None,
    ) -> None:
        """注入节点、存储、工具和子 Agent 管理器依赖。"""
        self.session_manager = session_manager
        self.message_store = message_store
        self.short_memory = short_memory
        self.query_rewrite_node = query_rewrite_node
        self.intent_recognition_node = intent_recognition_node
        self.context_builder = context_builder
        self.subagent_manager = subagent_manager
        self.tool_registry = tool_registry
        self.checkpointer = checkpointer or MemorySaver()

    def build(self):
        """构建真实 StateGraph，并注册 TASK1.md 要求的全部节点。"""
        graph = StateGraph(AgentGraphState)
        graph.add_node("load_session", self.load_session)
        graph.add_node("save_user_message", self.save_user_message)
        graph.add_node("query_rewrite", self.query_rewrite)
        graph.add_node("intent_recognition", self.intent_recognition)
        graph.add_node("build_orchestrator_context", self.build_orchestrator_context)
        graph.add_node("route_intent", self.route_intent)
        graph.add_node("call_troubleshooting_agent", self.call_troubleshooting_agent)
        graph.add_node("call_compliance_security_agent", self.call_compliance_security_agent)
        graph.add_node("call_document_parse_agent", self.call_document_parse_agent)
        graph.add_node("call_change_impact_analysis_agent", self.call_change_impact_analysis_agent)
        graph.add_node("direct_answer", self.direct_answer)
        graph.add_node("save_assistant_message", self.save_assistant_message)
        graph.add_node("compress_short_memory", self.compress_short_memory)
        graph.add_node("finalize_response", self.finalize_response)

        graph.set_entry_point("load_session")
        # 固定主干流程：session -> save user -> rewrite -> intent -> context。
        graph.add_edge("load_session", "save_user_message")
        graph.add_edge("save_user_message", "query_rewrite")
        graph.add_edge("query_rewrite", "intent_recognition")
        graph.add_edge("intent_recognition", "build_orchestrator_context")
        graph.add_edge("build_orchestrator_context", "route_intent")
        graph.add_conditional_edges(
            "route_intent",
            self.select_route,
            {
                "troubleshooting": "call_troubleshooting_agent",
                "compliance_review": "call_compliance_security_agent",
                "document_parse": "call_document_parse_agent",
                "change_impact_analysis": "call_change_impact_analysis_agent",
                "direct": "direct_answer",
            },
        )
        # 两条业务分支都会回到固定收尾链路。
        graph.add_edge("call_troubleshooting_agent", "save_assistant_message")
        graph.add_edge("call_compliance_security_agent", "save_assistant_message")
        graph.add_edge("call_document_parse_agent", "save_assistant_message")
        graph.add_edge("call_change_impact_analysis_agent", "save_assistant_message")
        graph.add_edge("direct_answer", "save_assistant_message")
        graph.add_edge("save_assistant_message", "compress_short_memory")
        graph.add_edge("compress_short_memory", "finalize_response")
        graph.add_edge("finalize_response", END)
        return graph.compile(checkpointer=self.checkpointer)

    async def load_session(self, state: AgentGraphState) -> dict[str, Any]:
        """加载 session 的 recent messages 和 short summary。"""
        self._log_node_enter(state, "load_session")
        session = await self.session_manager.load_session(state["session_key"])
        log_event(
            "session_loaded",
            **self._log_context(state, "load_session"),
            message="Session loaded",
            data={
                "recent_message_count": len(session["recent_messages"]),
                "has_short_summary": bool(session["short_summary"]),
            },
        )
        self._log_node_exit(state, "load_session")
        return {
            "recent_messages": session["recent_messages"],
            "short_summary": session["short_summary"],
            "graph_path": self._append_path(state, "load_session"),
        }

    async def save_user_message(self, state: AgentGraphState) -> dict[str, Any]:
        """保存用户原始消息，metadata 中保留关键追踪字段。"""
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
        log_event(
            "user_message_saved",
            **self._log_context(state, "save_user_message"),
            message="User message saved",
            data={"content_preview": preview_text(state["original_query"])},
        )
        self._log_node_exit(state, "save_user_message")
        return {"graph_path": self._append_path(state, "save_user_message")}

    async def query_rewrite(self, state: AgentGraphState) -> dict[str, Any]:
        """调用 QueryRewriteNode 执行固定前置改写。"""
        self._log_node_enter(state, "query_rewrite")
        log_event(
            "query_rewrite_started",
            **self._log_context(state, "query_rewrite"),
            message="Query rewrite started",
            data={
                "original_query_preview": preview_text(state["original_query"]),
                "recent_message_count": len(state.get("recent_messages", [])),
                "used_short_summary": bool(state.get("short_summary")),
            },
        )
        result = await self.query_rewrite_node.rewrite(
            original_query=state["original_query"],
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
        )
        log_event(
            "query_rewrite_finished",
            **self._log_context(state, "query_rewrite"),
            message="Query rewrite finished",
            data={"rewritten_query_preview": preview_text(result.rewritten_query)},
        )
        self._log_node_exit(state, "query_rewrite")
        return {
            "rewritten_query": result.rewritten_query,
            "graph_path": self._append_path(state, "query_rewrite"),
        }

    async def intent_recognition(self, state: AgentGraphState) -> dict[str, Any]:
        """调用 IntentRecognitionNode 识别意图并写入路由依据。"""
        self._log_node_enter(state, "intent_recognition")
        log_event(
            "intent_recognition_started",
            **self._log_context(state, "intent_recognition"),
            message="Intent recognition started",
            data={"rewritten_query_preview": preview_text(state.get("rewritten_query", state["original_query"]))},
        )
        result = await self.intent_recognition_node.recognize(
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
        )
        log_event(
            "intent_recognition_finished",
            **self._log_context(state, "intent_recognition"),
            message="Intent recognition finished",
            data={
                "intent": result.intent,
                "confidence": result.confidence,
                "target_subagent": result.target_subagent,
                "required_tools": result.required_tools,
                "used_short_summary": bool(state.get("short_summary")),
                "recent_message_count": len(state.get("recent_messages", [])),
            },
        )
        self._log_node_exit(state, "intent_recognition")
        return {
            "intent": result.intent,
            "confidence": result.confidence,
            "target_subagent": result.target_subagent,
            "required_tools": result.required_tools,
            "graph_path": self._append_path(state, "intent_recognition"),
        }

    async def build_orchestrator_context(self, state: AgentGraphState) -> dict[str, Any]:
        """构建主 Agent 协调上下文，不做任务级深度检索。"""
        self._log_node_enter(state, "build_orchestrator_context")
        context = await self.context_builder.build_for_orchestrator(
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            intent=state.get("intent", "unknown"),
            session_key=state["session_key"],
            recent_messages=state.get("recent_messages", []),
            short_summary=state.get("short_summary"),
            available_subagents=self.subagent_manager.list_agents(),
            available_tools=self.tool_registry.list_tools(),
        )
        log_event(
            "orchestrator_context_built",
            **self._log_context(state, "build_orchestrator_context"),
            message="Orchestrator context built",
            data={
                "knowledge_hint_count": len(context.lightweight_knowledge_hints),
                "available_subagents": context.available_subagents,
                "available_tools": context.available_tools,
            },
        )
        self._log_node_exit(state, "build_orchestrator_context")
        return {
            "orchestrator_context": context.model_dump(),
            "graph_path": self._append_path(state, "build_orchestrator_context"),
        }

    async def route_intent(self, state: AgentGraphState) -> dict[str, Any]:
        """显式路由节点，便于 trace 中看到条件路由发生位置。"""
        self._log_node_enter(state, "route_intent")
        route_nodes = {
            "troubleshooting": "call_troubleshooting_agent",
            "compliance_review": "call_compliance_security_agent",
            "document_parse": "call_document_parse_agent",
            "change_impact_analysis": "call_change_impact_analysis_agent",
        }
        next_node = route_nodes.get(str(state.get("intent")), "direct_answer")
        log_event(
            "route_decision",
            **self._log_context(state, "route_intent"),
            message="Route decision made",
            data={"intent": state.get("intent"), "next_node": next_node},
        )
        self._log_node_exit(state, "route_intent")
        return {"graph_path": self._append_path(state, "route_intent")}

    def select_route(self, state: AgentGraphState) -> str:
        """LangGraph 条件路由函数。"""
        if state.get("intent") == "troubleshooting":
            return "troubleshooting"
        if state.get("intent") == "compliance_review":
            return "compliance_review"
        if state.get("intent") == "document_parse":
            return "document_parse"
        if state.get("intent") == "change_impact_analysis":
            return "change_impact_analysis"
        return "direct"

    async def call_troubleshooting_agent(self, state: AgentGraphState) -> dict[str, Any]:
        """把 troubleshooting 任务交给固定 catalog 中的问题排查子 Agent。"""
        self._log_node_enter(state, "call_troubleshooting_agent")
        context = OrchestratorContext(**state["orchestrator_context"])
        task = SubAgentTask(
            name="troubleshooting_agent",
            query=state.get("rewritten_query", state["original_query"]),
            intent=state.get("intent", "troubleshooting"),
            session_key=state["session_key"],
            original_query=state["original_query"],
            metadata={"request_id": state["request_id"], "trace_id": state["trace_id"]},
        )
        log_event(
            "subagent_selected",
            **self._log_context(state, "call_troubleshooting_agent"),
            message="Subagent selected",
            data={"subagent_name": "troubleshooting_agent", "intent": state.get("intent")},
        )
        result = await self.subagent_manager.call_subagent("troubleshooting_agent", task, context)
        self._log_node_exit(state, "call_troubleshooting_agent")
        return {
            "subagent_result": result.model_dump(),
            "answer": result.answer,
            "selected_skill_id": result.selected_skill_id,
            "selected_skill_metadata": result.selected_skill_metadata,
            "skill_selection_score": result.skill_selection_score,
            "skill_selection_reason": result.skill_selection_reason,
            "graph_path": self._append_path(state, "call_troubleshooting_agent"),
        }

    async def call_compliance_security_agent(self, state: AgentGraphState) -> dict[str, Any]:
        """把 compliance_review 任务交给固定 catalog 中的合规安全子 Agent。"""
        return await self._call_catalog_agent(
            state=state,
            agent_name="compliance_security_agent",
            node_name="call_compliance_security_agent",
        )

    async def call_document_parse_agent(self, state: AgentGraphState) -> dict[str, Any]:
        """把 document_parse 任务交给固定 catalog 中的文档解析子 Agent。"""
        return await self._call_catalog_agent(
            state=state,
            agent_name="document_parse_agent",
            node_name="call_document_parse_agent",
        )

    async def call_change_impact_analysis_agent(self, state: AgentGraphState) -> dict[str, Any]:
        """把 change_impact_analysis 任务交给固定 catalog 中的变更影响分析子 Agent。"""
        return await self._call_catalog_agent(
            state=state,
            agent_name="change_impact_analysis_agent",
            node_name="call_change_impact_analysis_agent",
        )

    async def _call_catalog_agent(
        self,
        *,
        state: AgentGraphState,
        agent_name: str,
        node_name: str,
    ) -> dict[str, Any]:
        """调用固定 Agent Catalog 中的非排障子 Agent，并写回统一 graph state。"""
        self._log_node_enter(state, node_name)
        context = OrchestratorContext(**state["orchestrator_context"])
        task = SubAgentTask(
            name=agent_name,
            query=state.get("rewritten_query", state["original_query"]),
            intent=state.get("intent", "unknown"),
            session_key=state["session_key"],
            original_query=state["original_query"],
            metadata={"request_id": state["request_id"], "trace_id": state["trace_id"]},
        )
        log_event(
            "subagent_selected",
            **self._log_context(state, node_name),
            message="Subagent selected",
            data={"subagent_name": agent_name, "intent": state.get("intent")},
        )
        result = await self.subagent_manager.call_subagent(agent_name, task, context)
        self._log_node_exit(state, node_name)
        return {
            "subagent_result": result.model_dump(),
            "answer": result.answer,
            "selected_skill_id": result.selected_skill_id,
            "selected_skill_metadata": result.selected_skill_metadata,
            "skill_selection_score": result.skill_selection_score,
            "skill_selection_reason": result.skill_selection_reason,
            "graph_path": self._append_path(state, node_name),
        }

    async def direct_answer(self, state: AgentGraphState) -> dict[str, Any]:
        """处理非 troubleshooting 的轻量直接回答分支。"""
        self._log_node_enter(state, "direct_answer")
        intent = state.get("intent", "unknown")
        if intent == "product_rule_qa":
            answer = "当前第一阶段 MVP 仅提供产品规则问答的轻量入口，真实条款知识库尚未接入。"
        else:
            answer = "当前问题未识别为问题排查意图。请补充 requestId、错误码或接口返回信息。"
        self._log_node_exit(state, "direct_answer")
        return {"answer": answer, "graph_path": self._append_path(state, "direct_answer")}

    async def save_assistant_message(self, state: AgentGraphState) -> dict[str, Any]:
        """保存 assistant 回复，保留 original_query、rewritten_query 和 intent。"""
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
                "session_key": state["session_key"],
            },
        )
        log_event(
            "assistant_message_saved",
            **self._log_context(state, "save_assistant_message"),
            message="Assistant message saved",
            data={"answer_preview": preview_text(state.get("answer", ""))},
        )
        self._log_node_exit(state, "save_assistant_message")
        return {"graph_path": self._append_path(state, "save_assistant_message")}

    async def compress_short_memory(self, state: AgentGraphState) -> dict[str, Any]:
        """每轮回答后固定触发短期记忆压缩。"""
        self._log_node_enter(state, "compress_short_memory")
        summary = await self.short_memory.compress_after_turn(
            session_key=state["session_key"],
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            intent=state.get("intent", "unknown"),
            answer=state.get("answer", ""),
            subagent_result=state.get("subagent_result"),
        )
        log_event(
            "short_memory_compressed",
            **self._log_context(state, "compress_short_memory"),
            message="Short memory compressed",
            data={"summary_preview": preview_text(summary), "intent": state.get("intent")},
        )
        self._log_node_exit(state, "compress_short_memory")
        return {"short_summary": summary, "graph_path": self._append_path(state, "compress_short_memory")}

    async def finalize_response(self, state: AgentGraphState) -> dict[str, Any]:
        """最终节点，当前只追加 trace 路径，响应适配器负责对外格式。"""
        self._log_node_enter(state, "finalize_response")
        log_event(
            "response_finalized",
            **self._log_context(state, "finalize_response"),
            message="Graph response finalized",
            data={"intent": state.get("intent"), "answer_preview": preview_text(state.get("answer", ""))},
        )
        self._log_node_exit(state, "finalize_response")
        return {"graph_path": self._append_path(state, "finalize_response")}

    @staticmethod
    def _append_path(state: AgentGraphState, node: str) -> list[str]:
        """记录节点流转路径，方便测试证明走了真实图分支。"""
        return [*state.get("graph_path", []), node]

    @staticmethod
    def _log_context(state: AgentGraphState, node: str) -> dict[str, Any]:
        """从 graph state 提取标准日志上下文。"""
        return {
            "request_id": state.get("request_id"),
            "trace_id": state.get("trace_id"),
            "session_key": state.get("session_key"),
            "user_id": state.get("user_id"),
            "tenant_id": state.get("tenant_id"),
            "node": node,
        }

    def _log_node_enter(self, state: AgentGraphState, node: str) -> None:
        """记录 LangGraph 节点进入。"""
        log_event(
            "langgraph_node_enter",
            **self._log_context(state, node),
            message=f"Enter LangGraph node {node}",
            data={"node": node},
        )

    def _log_node_exit(self, state: AgentGraphState, node: str) -> None:
        """记录 LangGraph 节点退出。"""
        log_event(
            "langgraph_node_exit",
            **self._log_context(state, node),
            message=f"Exit LangGraph node {node}",
            data={"node": node},
        )
