from __future__ import annotations

"""AgentOrchestrator：LangGraph 的执行入口。"""

from app.runtime.checkpoint import SQLiteCheckpointStore
from app.runtime.graph_state import AgentGraphState
from app.schemas.message import InboundMessage


class AgentOrchestrator:
    """包装已编译的 LangGraph，隐藏 thread_id 配置细节。"""

    def __init__(self, graph, checkpoint_store: SQLiteCheckpointStore | None = None) -> None:
        """注入已编译的 LangGraph runnable 和项目内 checkpoint store。"""
        self.graph = graph
        self.checkpoint_store = checkpoint_store

    async def run(self, inbound: InboundMessage) -> AgentGraphState:
        """以 session_key 作为 thread_id 执行状态机，并保存最终 state。"""
        initial_state: AgentGraphState = {
            "request_id": inbound.request_id,
            "trace_id": inbound.trace_id,
            "tenant_id": inbound.tenant_id,
            "channel": inbound.channel,
            "user_id": inbound.user_id,
            "session_id": inbound.session_id,
            "session_key": inbound.session_key,
            "original_query": inbound.original_query,
            "error": None,
            "graph_path": [],
        }
        config = {"configurable": {"thread_id": inbound.session_key}}
        state = await self.graph.ainvoke(initial_state, config=config)
        if self.checkpoint_store is not None:
            await self.checkpoint_store.save(inbound.session_key, state)
        return state
