from __future__ import annotations

"""Agent 执行模式。"""

from app.schemas.enums.base import DescribedStrEnum


class ExecutionMode(DescribedStrEnum):
    INITIAL = ("initial", "首次执行用户任务。")
    REPAIR = ("repair", "根据任务完成度验收结果继续修复执行。")

