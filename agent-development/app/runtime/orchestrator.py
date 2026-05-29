from __future__ import annotations

"""AgentOrchestrator：LangGraph 的执行入口。"""

from app.runtime.checkpoint import SQLiteCheckpointStore
from app.runtime.graph_state import AgentGraphState
from app.schemas.approval import ApprovalRequest
from app.schemas.message import InboundMessage


class AgentOrchestrator:
    """包装已编译的 LangGraph，隐藏 thread_id 配置细节。"""

    def __init__(self, graph, checkpoint_store: SQLiteCheckpointStore | None = None) -> None:
        """注入已编译的 LangGraph runnable 和项目内 checkpoint store。"""
        self.graph = graph
        self.checkpoint_store = checkpoint_store

    async def run(self, inbound: InboundMessage) -> AgentGraphState:
        """Use a per-request thread_id to run the graph and save the final state snapshot."""
        thread_id = self._thread_id(inbound.session_key, inbound.request_id)
        initial_state: AgentGraphState = {
            "request_id": inbound.request_id,
            "trace_id": inbound.trace_id,
            "tenant_id": inbound.tenant_id,
            "channel": inbound.channel,
            "user_id": inbound.user_id,
            "session_id": inbound.session_id,
            "session_key": inbound.session_key,
            "thread_id": thread_id,
            "original_query": inbound.original_query,
            "error": None,
            "graph_path": [],
        }
        config = {"configurable": {"thread_id": thread_id}}
        state = await self.graph.ainvoke(initial_state, config=config)
        if self.checkpoint_store is not None:
            await self.checkpoint_store.save(thread_id, state)
        return state

    async def resume_after_approval(self, approval_request: ApprovalRequest) -> AgentGraphState:
        """Resume the graph thread after the external approval callback approves one tool."""
        thread_id = approval_request.thread_id or self._thread_id(
            approval_request.session_key or "",
            approval_request.request_id or approval_request.approval_id,
        )
        base_state = approval_request.resume_state or approval_request.pending_state
        resume_state: AgentGraphState = {
            **base_state,
            "approval_resume": True,
            "approval_id": approval_request.approval_id,
            "approval_request": approval_request.model_dump(),
            "approval_status": approval_request.status,
            "current_approval_id": approval_request.approval_id,
            "root_approval_id": approval_request.root_approval_id or approval_request.approval_id,
            "approval_depth": approval_request.approval_depth,
            "thread_id": thread_id,
            "session_key": approval_request.session_key or base_state.get("session_key", ""),
            "request_id": approval_request.request_id or base_state.get("request_id", approval_request.approval_id),
            "trace_id": approval_request.trace_id or base_state.get("trace_id"),
            "pending_messages": approval_request.pending_messages,
            "pending_tools": approval_request.pending_tools,
            "pending_tool_call": approval_request.pending_tool_call,
        }
        config = {"configurable": {"thread_id": thread_id}}
        state = await self.graph.ainvoke(resume_state, config=config)
        if self.checkpoint_store is not None:
            await self.checkpoint_store.save(thread_id, state)
        return state

    @staticmethod
    def _thread_id(session_key: str, request_id: str) -> str:
        return f"{session_key}:{request_id}"
