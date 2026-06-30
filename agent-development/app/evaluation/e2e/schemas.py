from __future__ import annotations

"""Dynamic E2E Eval 的用例模型。

这一层只描述“从 /api/chat 等价输入开始”的真实链路评测数据，不复用
AgentEvalFakeLLM 的脚本字段，避免动态 E2E 退化成确定性 Agent Eval。
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluation.agent.schemas import AgentEvalExpected, RiskLevel


TransportMode = Literal["orchestrator", "http"]
LLMMode = Literal["real"]


class DynamicE2EMessage(BaseModel):
    """动态 E2E 输入中的一条消息，结构与 ChatMessage 保持一致。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DynamicE2EInput(BaseModel):
    """一次 `/api/chat` 等价请求输入。"""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = "tenant"
    channel: str = "web"
    user_id: str = "u1"
    session_id: str = "s1"
    messages: list[DynamicE2EMessage]
    result_callback_url: str | None = None

    @model_validator(mode="after")
    def validate_messages(self) -> "DynamicE2EInput":
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("DynamicE2EInput.messages must include a user message")
        return self


class DynamicE2EExpected(AgentEvalExpected):
    """动态 E2E 复用 Agent 行为断言字段。

    Expected 仍是测试期结构，不参与生产运行；真实运行链路只看 ChatRequest、
    Settings、当前 `.env` 和项目运行时代码。
    """


class DynamicE2ECase(BaseModel):
    """一个真实 LLM 动态 E2E 用例。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    description: str = ""
    transport: TransportMode = "orchestrator"
    llm_mode: LLMMode = "real"
    input: DynamicE2EInput
    expected: DynamicE2EExpected
    tags: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    settings_overrides: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_case(self) -> "DynamicE2ECase":
        if not self.case_id.strip():
            raise ValueError("case_id is required")
        return self


class DynamicE2ESuite(BaseModel):
    """一组动态 E2E 用例。"""

    model_config = ConfigDict(extra="forbid")

    suite: str
    description: str = ""
    cases: list[DynamicE2ECase]

    @model_validator(mode="after")
    def validate_suite(self) -> "DynamicE2ESuite":
        if not self.suite.strip():
            raise ValueError("suite is required")
        if not self.cases:
            raise ValueError(f"dynamic e2e suite {self.suite} must include cases")
        ids = [case.case_id for case in self.cases]
        duplicate_ids = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
        if duplicate_ids:
            raise ValueError(f"dynamic e2e suite {self.suite} has duplicate case ids: {duplicate_ids}")
        return self
