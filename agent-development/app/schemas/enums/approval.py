from __future__ import annotations

"""人工审批状态和事件类型。"""

from app.schemas.enums.base import DescribedStrEnum


class ApprovalStatus(DescribedStrEnum):
    CREATED = ("created", "本地审批请求已创建。")
    PENDING = ("pending", "审批请求已提交，等待审批系统回调。")
    APPROVED = ("approved", "审批已通过，等待或正在恢复工具执行。")
    EXECUTING = ("executing", "审批通过后的工具正在执行。")
    REJECTED = ("rejected", "审批被拒绝。")
    EXPIRED = ("expired", "审批已过期。")
    SUBMIT_FAILED = ("submit_failed", "审批请求提交外部系统失败。")
    COMPLETED = ("completed", "审批恢复链路已完成。")
    FAILED = ("failed", "审批恢复链路失败。")
    MANUAL_INTERVENTION_REQUIRED = ("manual_intervention_required", "审批链路需要人工接管。")


class ApprovalCallbackStatus(DescribedStrEnum):
    APPROVED = ("approved", "外部审批系统回调审批通过。")
    REJECTED = ("rejected", "外部审批系统回调审批拒绝。")


class ApprovalEventType(DescribedStrEnum):
    CREATED = ("created", "审批请求已创建事件。")
    SUBMITTED = ("submitted", "审批请求已提交事件。")
    SUBMIT_FAILED = ("submit_failed", "审批请求提交失败事件。")
    APPROVED = ("approved", "审批通过事件。")
    REJECTED = ("rejected", "审批拒绝事件。")
    COMPLETED = ("completed", "审批恢复完成事件。")
    COMPLETED_WITH_NEXT_APPROVAL = ("completed_with_next_approval", "当前审批完成后又触发下一次审批。")
    MANUAL_INTERVENTION_REQUIRED = ("manual_intervention_required", "审批链路需要人工接管事件。")
    NEXT_APPROVAL_CREATED = ("next_approval_created", "下一笔审批请求已创建事件。")
    RESULT_CALLBACK_DELIVERED = ("result_callback_delivered", "最终结果回调已送达。")
    RESULT_CALLBACK_FAILED = ("result_callback_failed", "最终结果回调失败。")
    SUBMIT_FAILED_ANSWER_PREPARED = ("submit_failed_answer_prepared", "审批提交失败的外发答案已生成。")

