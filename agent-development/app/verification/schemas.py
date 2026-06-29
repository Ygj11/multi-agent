from __future__ import annotations

"""通用 VerificationService 的输入输出协议。

这些 schema 只服务于 `app.verification.service.VerificationService`：

- `VerificationInput` 描述某个运行阶段要校验的上下文；
- `VerificationResult` 描述 verifier 的处理意见，例如 allow、patch、block、manual、retry。

不要把它和 `task_completion/schemas.py` 混用。后者表达的是任务完成度验收，
例如 PASS / CONTINUE / NEED_USER；这里表达的是运行时安全策略动作。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


VerificationStage = Literal["request_access", "agent_access", "pre_skill", "pre_tool", "post_tool", "pre_answer"]
VerificationAction = Literal["allow", "patch", "block", "manual", "retry"]


class VerificationInput(BaseModel):
    """一次通用验证请求。

    典型调用场景：
    - `pre_tool`：ToolExecutor 在真正执行工具前调用，可检查工具参数和上下文；
    - `pre_answer`：Graph 在最终答案返回用户前调用，可做脱敏、拦截或安全改写；
    - 其他 stage 是预留边界，只有注册的 verifier 声明支持该 stage 时才会执行。
    """

    stage: VerificationStage
    request_id: str | None = None
    trace_id: str | None = None
    session_key: str | None = None
    # 可信身份快照。Authorization 负责权限判定；Verifier 可以用它判断答案外发时
    # 是否需要按角色/数据权限脱敏。
    principal: dict[str, Any] | None = None
    auth_context: dict[str, Any] = Field(default_factory=dict)
    agent_name: str | None = None
    skill_id: str | None = None
    # pre_tool / post_tool 阶段使用的工具上下文。
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    tool_result: Any | None = None
    # pre_answer 阶段使用的候选最终答案。
    answer: str | None = None
    # 轻量证据摘要；不要把完整敏感工具原文塞入这里。
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    """某个 verifier 对本次验证的决定。

    action 语义：
    - allow：通过；
    - patch：允许但需要替换输出，例如脱敏后的 answer；
    - block：阻断；
    - manual：需要人工处理；
    - retry：建议上游重新生成或修复答案。
    """

    passed: bool
    stage: str
    verifier_name: str
    severity: Literal["info", "warning", "error", "blocking"] = "info"
    action: VerificationAction = "allow"
    code: str | None = None
    reason: str | None = None
    patched_output: Any | None = None
    redactions: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
