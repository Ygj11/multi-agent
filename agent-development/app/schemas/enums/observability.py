from __future__ import annotations

"""结构化日志中的稳定事件名。"""

from app.schemas.enums.base import DescribedStrEnum


class RuntimeEvent(DescribedStrEnum):
    REQUEST_RECEIVED = ("request_received", "API 收到请求。")
    REQUEST_ADAPTED = ("request_adapted", "请求已转换为内部 InboundMessage。")
    RESPONSE_RETURNED = ("response_returned", "API 已返回响应。")
    RESPONSE_FINALIZED = ("response_finalized", "Graph 或 ResponseAdapter 已形成最终响应。")
    LANGGRAPH_NODE_ENTER = ("langgraph_node_enter", "LangGraph 节点开始执行。")
    LANGGRAPH_NODE_EXIT = ("langgraph_node_exit", "LangGraph 节点执行完成。")
    INVALID_TASK_COMPLETION_RESULT = ("invalid_task_completion_result", "任务完成度验收结果无法按 schema 恢复。")
    INVALID_PRE_ANSWER_VERIFICATION_RESULT = ("invalid_pre_answer_verification_result", "最终外发验证结果无法按 schema 恢复。")
    TOOL_CALLING_RUNNER_STARTED = ("tool_calling_runner_started", "子 Agent 工具循环开始。")
    TOOL_EXECUTION_FINISHED = ("tool_execution_finished", "工具执行结束。")
    EVIDENCE_SAVE_FAILED = ("evidence_save_failed", "工具证据保存失败。")
    LLM_CHAT_FINISHED = ("llm_chat_finished", "LLM 调用结束。")
    TASK_COMPLETION_HANDOFF = ("task_completion_handoff", "任务完成度验收转人工接管。")
