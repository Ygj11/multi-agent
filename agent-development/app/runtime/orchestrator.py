from __future__ import annotations

"""AgentOrchestrator：LangGraph 的执行入口。"""

from app.runtime.checkpoint import SQLiteCheckpointStore
from app.runtime.graph_state import AgentGraphState
from app.runtime.state_contracts import AgentResumeState
from app.runtime.state_projector import project_checkpoint_snapshot
from app.schemas.approval import ApprovalRequest
from app.schemas.message import InboundMessage


class AgentOrchestrator:
    """包装已编译的 LangGraph，隐藏 thread_id 与 checkpoint 细节。

    Orchestrator 是运行时入口，不做节点编排，也不直接读写业务存储。
    普通请求从 InboundMessage 构造初始 State；审批恢复请求从 ApprovalStore
    保存的 resume_state 重建 State，再重新进入 Graph 的恢复分支。
    """

    def __init__(self, graph, checkpoint_store: SQLiteCheckpointStore | None = None) -> None:
        """注入已编译的 LangGraph runnable 和项目内 checkpoint store。"""
        self.graph = graph
        self.checkpoint_store = checkpoint_store

    async def run(self, inbound: InboundMessage) -> AgentGraphState:
        """执行一次普通请求，并在结束后保存最终状态快照。"""
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
            "auth_context": inbound.auth_context,
            "original_query": inbound.original_query,
            "error": None,
            "graph_path": [],
        }
        config = {"configurable": {"thread_id": thread_id}}
        state = await self.graph.ainvoke(initial_state, config=config)
        if self.checkpoint_store is not None:
            await self.checkpoint_store.save_snapshot(thread_id, project_checkpoint_snapshot(state))
        return state

    async def resume_after_approval(self, approval_request: ApprovalRequest) -> AgentGraphState:
        """审批通过后恢复 Graph。

        当前实现不是 LangGraph 原生 interrupt/resume。中断时由 ApprovalStore
        保存必要的 resume_state、pending_messages、pending_tools 和 pending_tool_call；
        回调通过这些持久化内容重建 State，并从 route_entry 的恢复分支继续执行。
        """
        thread_id = approval_request.thread_id or self._thread_id(
            approval_request.session_key or "",
            approval_request.request_id or approval_request.approval_id,
        )
        base_state = approval_request.resume_state or approval_request.pending_state
        resume_contract = AgentResumeState.model_validate(base_state)
        resume_state: AgentGraphState = {
            **resume_contract.to_graph_state(),
            "approval_resume": True,
            "approval_id": approval_request.approval_id,
            "approval_status": approval_request.status,
            "current_approval_id": approval_request.approval_id,
            "root_approval_id": approval_request.root_approval_id or approval_request.approval_id,
            "parent_approval_id": approval_request.parent_approval_id,
            "approval_depth": approval_request.approval_depth,
            "thread_id": thread_id,
            "session_key": approval_request.session_key or resume_contract.session_key,
            "request_id": approval_request.request_id or resume_contract.request_id,
            "trace_id": approval_request.trace_id or resume_contract.trace_id,
            "auth_context": approval_request.auth_context_snapshot or None,
            "pending_messages": approval_request.pending_messages,
            "pending_tools": approval_request.pending_tools,
            "pending_tool_call": approval_request.pending_tool_call,
        }
        config = {"configurable": {"thread_id": thread_id}}
        state = await self.graph.ainvoke(resume_state, config=config)
        if self.checkpoint_store is not None:
            await self.checkpoint_store.save_snapshot(thread_id, project_checkpoint_snapshot(state))
        return state

    @staticmethod
    def _thread_id(session_key: str, request_id: str) -> str:
        return f"{session_key}:{request_id}"
