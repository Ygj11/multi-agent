from __future__ import annotations

"""Agent 行为级 Eval 的用例、轨迹和报告模型。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RiskLevel = Literal["low", "medium", "high"]
FinalOutcome = Literal[
    "answered",
    "need_user",
    "human_handoff",
    "failed",
    "approval_pending",
    "approval_completed",
    "compliance_blocked",
]


class AgentEvalMessage(BaseModel):
    """一条输入消息 fixture。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentEvalInput(BaseModel):
    """一次 /api/chat 等价输入。"""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = "tenant"
    channel: str = "web"
    user_id: str = "u1"
    session_id: str = "s1"
    messages: list[AgentEvalMessage]

    @model_validator(mode="after")
    def validate_messages(self) -> "AgentEvalInput":
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("AgentEvalInput.messages must include a user message")
        return self


class AgentEvalSessionFixture(BaseModel):
    """预置会话消息或摘要。"""

    model_config = ConfigDict(extra="forbid")

    recent_messages: list[AgentEvalMessage] = Field(default_factory=list)
    short_summary: str | None = None


class AgentEvalToolCallSpec(BaseModel):
    """Fake LLM 返回的 tool call。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class AgentEvalLLMResponseSpec(BaseModel):
    """Fake LLM 的单次响应定义。"""

    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    content_json: dict[str, Any] | None = None
    tool_calls: list[AgentEvalToolCallSpec] = Field(default_factory=list)
    finish_reason: str | None = None
    error: str | None = None
    model: str | None = "agent-eval-fake"

    @model_validator(mode="after")
    def validate_content(self) -> "AgentEvalLLMResponseSpec":
        if self.content is not None and self.content_json is not None:
            raise ValueError("content and content_json cannot both be set")
        return self


class AgentEvalLLMScriptedResponse(BaseModel):
    """按 scene 和顺序匹配的 Fake LLM 响应。"""

    model_config = ConfigDict(extra="forbid")

    scene: str
    response: AgentEvalLLMResponseSpec
    match_contains: list[str] = Field(default_factory=list)
    repeat: bool = False


class AgentEvalToolFixture(BaseModel):
    """覆盖某个已注册工具 callable 的 fixture。

    工具仍然通过真实 ToolExecutor 执行；这里仅替换最终业务 callable。
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    result: Any = Field(default_factory=dict)
    results: list[Any] | None = None
    expected_arguments: dict[str, Any] | None = None
    is_write: bool | None = None
    operation: str | None = None
    risk_level: str | None = None
    raise_error: str | None = None


class AgentEvalApprovalCallbackFixture(BaseModel):
    """审批回调 fixture；approval_id 默认使用最近一个 pending approval。"""

    model_config = ConfigDict(extra="forbid")

    approval_id: str | None = None
    external_approval_id: str | None = None
    status: Literal["approved", "rejected"] = "approved"
    approver: str = "agent_eval_manager"
    comment: str | None = None


class AgentEvalApprovalFixture(BaseModel):
    """Fake ApprovalSystemClient 行为。"""

    model_config = ConfigDict(extra="forbid")

    accepted: bool = True
    status: str = "pending"
    error: str | None = None
    callbacks: list[AgentEvalApprovalCallbackFixture] = Field(default_factory=list)


class AgentEvalBusinessStateFixture(BaseModel):
    """Fake BusinessStateProbe 输出。"""

    model_config = ConfigDict(extra="forbid")

    probe_name: str = "agent_eval_probe"
    supports_skill_id: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class AgentEvalExpected(BaseModel):
    """运行后断言。所有字段都是测试期 expected，不参与生产运行。"""

    model_config = ConfigDict(extra="forbid")

    selected_agent: str | None = None
    selected_skill_id: str | None = None
    initial_verifier_status: str | None = None
    final_verifier_status: str | None = None
    completion_status_must_not: list[str] = Field(default_factory=list)
    repair_count: int | None = None
    final_outcome: FinalOutcome | None = None
    approval_required: bool | None = None
    approval_status: str | None = None
    callback_final_status: str | None = None
    compliance_action: str | None = None
    graph_path_must_include: list[str] = Field(default_factory=list)
    graph_path_must_not_include: list[str] = Field(default_factory=list)
    tool_calls_must_include: list[str] = Field(default_factory=list)
    tool_calls_must_not_repeat: list[str] = Field(default_factory=list)
    forbidden_duplicate_actions: list[str] = Field(default_factory=list)
    max_repair_round: int | None = None
    approval_pending_skips_completion_verify: bool = False
    no_agent_drift: bool = True
    no_skill_drift: bool = True
    answer_must_include: list[str] = Field(default_factory=list)
    answer_must_not_include: list[str] = Field(default_factory=list)


class AgentEvalCase(BaseModel):
    """一个端到端 Agent 行为用例。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    description: str = ""
    input: AgentEvalInput
    session_fixtures: AgentEvalSessionFixture | None = None
    llm_scripted_responses: list[AgentEvalLLMScriptedResponse] = Field(default_factory=list)
    tool_fixtures: list[AgentEvalToolFixture] = Field(default_factory=list)
    approval_fixtures: AgentEvalApprovalFixture | None = None
    business_state_fixtures: list[AgentEvalBusinessStateFixture] = Field(default_factory=list)
    expected: AgentEvalExpected
    tags: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    settings_overrides: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_case(self) -> "AgentEvalCase":
        if not self.case_id.strip():
            raise ValueError("case_id is required")
        return self


class AgentEvalSuite(BaseModel):
    """一组端到端 Agent 行为用例。"""

    model_config = ConfigDict(extra="forbid")

    suite: str
    description: str = ""
    cases: list[AgentEvalCase]

    @model_validator(mode="after")
    def validate_suite(self) -> "AgentEvalSuite":
        if not self.suite.strip():
            raise ValueError("suite is required")
        if not self.cases:
            raise ValueError(f"agent eval suite {self.suite} must include cases")
        ids = [case.case_id for case in self.cases]
        duplicate_ids = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
        if duplicate_ids:
            raise ValueError(f"agent eval suite {self.suite} has duplicate case ids: {duplicate_ids}")
        return self


class AgentEvalLLMCallTrace(BaseModel):
    """一次 Fake LLM 调用摘要。"""

    scene: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    session_key: str | None = None
    tool_names: list[str] = Field(default_factory=list)
    matched_index: int | None = None
    exhausted: bool = False


class AgentEvalTrace(BaseModel):
    """Case 执行后的关键轨迹，避免保存完整 prompt 和敏感工具原文。"""

    request_id: str | None = None
    session_key: str | None = None
    answer: str | None = None
    graph_path: list[str] = Field(default_factory=list)
    selected_agent: str | None = None
    selected_skill_id: str | None = None
    repair_round: int = 0
    task_completion_statuses: list[str] = Field(default_factory=list)
    final_task_completion_status: str | None = None
    pre_answer_action: str | None = None
    approval_required: bool = False
    approval_id: str | None = None
    approval_status: str | None = None
    callback_statuses: list[str] = Field(default_factory=list)
    final_outcome: FinalOutcome = "answered"
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    llm_calls: list[AgentEvalLLMCallTrace] = Field(default_factory=list)
    assistant_message_metadata: list[dict[str, Any]] = Field(default_factory=list)
    state_summary: dict[str, Any] = Field(default_factory=dict)


class AgentEvalAssertionFailure(BaseModel):
    """断言失败详情。"""

    assertion: str
    expected: Any = None
    actual: Any = None
    message: str


class AgentEvalCaseResult(BaseModel):
    """单个 Agent Eval case 的结果。"""

    case_id: str
    suite: str
    passed: bool
    errors: list[str] = Field(default_factory=list)
    assertion_failures: list[AgentEvalAssertionFailure] = Field(default_factory=list)
    trace: AgentEvalTrace = Field(default_factory=AgentEvalTrace)
    duration_ms: int = 0
    risk_level: RiskLevel = "low"
    tags: list[str] = Field(default_factory=list)
    expected_initial_verifier_status: str | None = None
    expected_final_verifier_status: str | None = None


class AgentEvalMetrics(BaseModel):
    """报告级指标。"""

    total: int = 0
    passed: int = 0
    failed: int = 0
    first_pass_completion_rate: float = 0.0
    first_pass_failure_rate: float = 0.0
    verifier_pass_accuracy: float = 0.0
    verifier_incomplete_detection_rate: float = 0.0
    verifier_false_pass_rate: float = 0.0
    verifier_false_continue_rate: float = 0.0
    repair_attempt_rate: float = 0.0
    repair_success_rate: float = 0.0
    average_repair_rounds: float = 0.0
    no_progress_termination_rate: float = 0.0
    final_task_completion_rate: float = 0.0
    final_failure_rate: float = 0.0
    human_handoff_rate: float = 0.0
    need_user_rate: float = 0.0
    average_tool_calls: float = 0.0
    duplicate_tool_call_rate: float = 0.0
    average_llm_calls: float = 0.0
    average_latency_ms: float = 0.0
    infinite_loop_count: int = 0
    max_repair_round_violation_count: int = 0
    agent_drift_count: int = 0
    skill_drift_count: int = 0
    approval_bypass_count: int = 0


class AgentEvalSuiteResult(BaseModel):
    """单个 suite 的聚合结果。"""

    suite: str
    total: int
    passed: int
    failed: int
    metrics: AgentEvalMetrics
    cases: list[AgentEvalCaseResult]


class AgentEvalReport(BaseModel):
    """Agent Eval 总报告。"""

    total: int
    passed: int
    failed: int
    metrics: AgentEvalMetrics
    suites: list[AgentEvalSuiteResult]
