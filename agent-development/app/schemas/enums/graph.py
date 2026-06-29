from __future__ import annotations

"""LangGraph 节点名和条件路由机器值。"""

from app.schemas.enums.base import DescribedStrEnum


class GraphNode(DescribedStrEnum):
    ROUTE_ENTRY = ("route_entry", "入口分流节点，区分普通请求和审批恢复请求。")
    LOAD_SESSION = ("load_session", "加载会话历史、短摘要和最近消息。")
    RESUME_APPROVED_TOOL = ("resume_approved_tool", "审批通过后恢复被暂停的工具调用。")
    SAVE_USER_MESSAGE = ("save_user_message", "保存用户当前消息。")
    QUERY_REWRITE = ("query_rewrite", "将当前问题结合上下文改写为自包含请求。")
    INTENT_RECOGNITION = ("intent_recognition", "识别 intent/sub_intent。")
    BUILD_ORCHESTRATOR_CONTEXT = ("build_orchestrator_context", "构建主 Agent 父级上下文。")
    SELECT_AGENT = ("select_agent", "选择本次处理请求的子 Agent。")
    DISPATCH_AGENT = ("dispatch_agent", "分发任务给选中的子 Agent。")
    BUILD_CLARIFICATION_ANSWER = ("build_clarification_answer", "构建澄清回复。")
    CHECK_HUMAN_APPROVAL_REQUIRED = ("check_human_approval_required", "检查子 Agent 是否触发人工审批。")
    COLLECT_VERIFICATION_EVIDENCE = ("collect_verification_evidence", "收集任务完成度验收证据。")
    VERIFY_TASK_COMPLETION = ("verify_task_completion", "验证任务是否按 Skill SOP 完成。")
    BUILD_REPAIR_TASK = ("build_repair_task", "根据 RepairPlan 构建修复任务。")
    DISPATCH_REPAIR_AGENT = ("dispatch_repair_agent", "让原子 Agent 按固定 Skill 继续修复。")
    BUILD_VERIFICATION_CLARIFICATION = ("build_verification_clarification", "构建任务完成度补充信息问题。")
    BUILD_HANDOFF_ANSWER = ("build_handoff_answer", "构建人工接管回复。")
    CREATE_APPROVAL_REQUEST = ("create_approval_request", "创建人工审批请求。")
    SUBMIT_APPROVAL_REQUEST = ("submit_approval_request", "提交外部审批系统。")
    PAUSE_FOR_APPROVAL = ("pause_for_approval", "暂停当前流程并返回审批 pending 答案。")
    PRE_ANSWER_VERIFY = ("pre_answer_verify", "最终答案外发前验证。")
    REGENERATE_COMPLIANT_ANSWER = ("regenerate_compliant_answer", "按合规结果生成安全改写答案。")
    FALLBACK_ANSWER = ("fallback_answer", "构建安全降级答案。")
    SAVE_ASSISTANT_MESSAGE = ("save_assistant_message", "保存助手最终回复。")
    COMPRESS_SHORT_MEMORY = ("compress_short_memory", "压缩短期记忆。")
    FINALIZE_RESPONSE = ("finalize_response", "结束 Graph 并形成最终响应状态。")


class EntryRoute(DescribedStrEnum):
    RESUME = ("resume", "进入审批恢复路径。")
    NORMAL = ("normal", "进入普通请求路径。")


class ClarificationRoute(DescribedStrEnum):
    CLARIFY = ("clarify", "需要先向用户澄清。")
    CONTINUE = ("continue", "可以继续进入下一阶段。")


class ApprovalRequiredRoute(DescribedStrEnum):
    REQUIRED = ("required", "需要创建并提交人工审批。")
    NOT_REQUIRED = ("not_required", "无需审批，继续任务完成度验收。")
    SKIP_COMPLETION = ("skip_completion", "当前结果不进入任务完成度验收，直接外发前验证。")


class TaskCompletionRoute(DescribedStrEnum):
    PASSED = ("passed", "任务完成，进入最终答案验证。")
    CONTINUE = ("continue", "任务未完成，进入修复任务构建。")
    NEED_USER = ("need_user", "需要用户补充信息。")
    HANDOFF = ("handoff", "需要人工接管。")
    FAILED = ("failed", "任务完成度验证失败，进入安全降级。")


class AfterApprovalCreateRoute(DescribedStrEnum):
    SUBMIT = ("submit", "审批请求可提交到外部审批系统。")
    MANUAL = ("manual", "审批链路超限或无法自动继续，需要人工处理。")


class VerificationRoute(DescribedStrEnum):
    PASSED = ("passed", "最终答案验证通过。")
    RETRY = ("retry", "允许重新生成一次安全答案。")
    FALLBACK = ("fallback", "最终答案验证未通过，进入安全降级。")

