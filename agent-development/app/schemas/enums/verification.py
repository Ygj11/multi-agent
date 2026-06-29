from __future__ import annotations

"""通用 Verification 阶段、动作和严重级别。"""

from app.schemas.enums.base import DescribedStrEnum


class VerificationStage(DescribedStrEnum):
    REQUEST_ACCESS = ("request_access", "请求进入系统前的访问验证。")
    AGENT_ACCESS = ("agent_access", "进入 Agent 前的访问验证。")
    PRE_SKILL = ("pre_skill", "Skill 执行前验证。")
    PRE_TOOL = ("pre_tool", "工具执行前验证。")
    POST_TOOL = ("post_tool", "工具执行后验证。")
    PRE_ANSWER = ("pre_answer", "最终答案外发前验证。")


class VerificationAction(DescribedStrEnum):
    ALLOW = ("allow", "验证通过。")
    PATCH = ("patch", "允许继续，但需要替换输出。")
    BLOCK = ("block", "阻断当前输出或操作。")
    MANUAL = ("manual", "需要人工处理。")
    RETRY = ("retry", "建议上游重新生成或修复。")


class VerificationSeverity(DescribedStrEnum):
    INFO = ("info", "信息级验证结果。")
    WARNING = ("warning", "警告级验证结果。")
    ERROR = ("error", "错误级验证结果。")
    BLOCKING = ("blocking", "阻断级验证结果。")

