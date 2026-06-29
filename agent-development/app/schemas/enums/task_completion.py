from __future__ import annotations

"""任务完成度验收状态和路由。"""

from app.schemas.enums.base import DescribedStrEnum
from app.schemas.enums.graph import TaskCompletionRoute


class TaskCompletionStatus(DescribedStrEnum):
    PASS = ("PASS", "任务已经完成，可以进入最终回答合规验证。")
    CONTINUE = ("CONTINUE", "任务尚未完成，需要原任务子 Agent 继续执行。")
    NEED_USER = ("NEED_USER", "缺少任务执行所需的信息，需要用户补充。")
    HUMAN_HANDOFF = ("HUMAN_HANDOFF", "当前任务需要人工接管。")
    FAILED = ("FAILED", "任务执行或任务完成度验证失败。")


__all__ = ["TaskCompletionRoute", "TaskCompletionStatus"]

