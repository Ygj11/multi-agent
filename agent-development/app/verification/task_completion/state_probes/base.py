from __future__ import annotations

"""业务状态探针协议。"""

from typing import Protocol

from app.verification.task_completion.schemas import TaskCompletionVerificationContext, VerificationEvidence


class BusinessStateProbe(Protocol):
    """只读采集最终业务状态证据，不执行原任务。"""

    async def supports(self, context: TaskCompletionVerificationContext) -> bool:
        ...

    async def collect(self, context: TaskCompletionVerificationContext) -> list[VerificationEvidence]:
        ...

