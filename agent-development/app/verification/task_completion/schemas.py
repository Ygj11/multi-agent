from __future__ import annotations

"""Skill-aware 任务完成度验收 schema。

这里的模型只描述“任务是否已经按 Skill SOP 完成、是否需要继续修复”。
它与现有 pre-answer compliance verification 分离，后者只负责最终答案能否外发。
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TaskCompletionStatus = Literal["PASS", "CONTINUE", "NEED_USER", "HUMAN_HANDOFF", "FAILED"]


class VerificationEvidence(BaseModel):
    """给任务完成度 Verifier 的轻量证据摘要。

    证据可以来自工具结果、EvidenceStore 或状态探针，但这里不保存完整敏感原文；
    大字段应通过 evidence_id 或 tool log 引用回查。
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str | None = None
    source_type: str
    source_name: str
    summary: str
    status: Literal["available", "unavailable", "success", "failed", "pending"] = "available"
    tool_name: str | None = None
    tool_arguments_summary: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RepairPlan(BaseModel):
    """Verifier 输出的有限修复计划。

    RepairPlan 是“让原子 Agent 继续做什么”的计划，不是工具执行请求。
    后续仍必须回到原 selected_agent 和 pinned skill，通过 ToolExecutor 执行工具。
    """

    model_config = ConfigDict(extra="forbid")

    reason: str
    completed_items: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    do_not_repeat: list[str] = Field(default_factory=list)
    reuse_evidence_ids: list[str] = Field(default_factory=list)
    expected_new_evidence: list[str] = Field(default_factory=list)
    target_agent: str
    selected_skill_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    fingerprint: str | None = None

    @field_validator("reason", "target_agent", "selected_skill_id")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value.strip()


class TaskCompletionVerificationResult(BaseModel):
    """一次任务完成度验收结果。"""

    model_config = ConfigDict(extra="forbid")

    status: TaskCompletionStatus
    completed: bool
    summary: str
    completed_items: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    repair_plan: RepairPlan | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    verifier_name: str = "task_completion_verifier"
    llm_status: str | None = None
    fallback_reason: str | None = None

    @model_validator(mode="after")
    def _status_consistency(self) -> "TaskCompletionVerificationResult":
        if self.status == "PASS" and not self.completed:
            raise ValueError("PASS result must set completed=true")
        if self.status != "PASS" and self.completed:
            raise ValueError("non-PASS result must set completed=false")
        if self.status == "CONTINUE" and self.repair_plan is None:
            raise ValueError("CONTINUE result requires repair_plan")
        return self


class TaskCompletionVerificationContext(BaseModel):
    """Verifier 的结构化输入。

    完整 Skill 文本只在调用 Verifier 时加载进入 prompt，不进入 Graph State 或 checkpoint。
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    trace_id: str | None = None
    session_key: str
    original_query: str
    rewritten_query: str
    entities: dict[str, Any] = Field(default_factory=dict)
    selected_agent: str
    selected_skill_id: str
    selected_skill_version: str | None = None
    skill_name: str | None = None
    skill_content: str
    answer: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[VerificationEvidence] = Field(default_factory=list)
    stopped_reason: str | None = None
    repair_round: int = 0
    repair_history: list[dict[str, Any]] = Field(default_factory=list)
    original_subagent_result: dict[str, Any] = Field(default_factory=dict)
    previous_subagent_results: list[dict[str, Any]] = Field(default_factory=list)
    auth_context: dict[str, Any] | None = None
