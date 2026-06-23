from __future__ import annotations

"""AgentCard schemas used by orchestrator-side discovery and selection."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MemoryPolicy(BaseModel):
    """Controls how much conversation memory an agent receives."""

    use_short_summary: bool = True
    recent_turns: int = 5


class AgentAccessPolicy(BaseModel):
    """Agent-level access policy declared by AgentCard.

    This controls whether a principal may enter a sub-agent at all. Tool-level
    scopes and resource ownership are checked later by ToolExecutor guards.
    空列表不增加 AgentCard 级别的额外限制；全局认证和 ToolExecutor
    的权限校验仍然生效。
    """

    required_roles: list[str] = Field(default_factory=list)
    required_scopes: list[str] = Field(default_factory=list)
    required_data_permissions: list[str] = Field(default_factory=list)
    allowed_org_types: list[str] = Field(default_factory=list)
    allowed_org_ids: list[str] = Field(default_factory=list)
    denied_org_ids: list[str] = Field(default_factory=list)


class MCPPolicy(BaseModel):
    """Controls whether an agent may use discovered MCP tools.

    MCP 工具暴露采用显式开启：未配置时 ``enabled`` 保持为 ``false``。
    """

    enabled: bool = False


class AgentCard(BaseModel):
    """Structured description of a sub agent discoverable by the main agent."""

    agent_name: str
    display_name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    supported_intents: list[str] = Field(default_factory=list)
    supported_sub_intents: list[str] = Field(default_factory=list)
    # 严格路由白名单。卡片必须声明路由；子列表为空表示该父 intent 在
    # 当前卡片中没有合法 sub_intent。
    supported_routes: dict[str, list[str]] = Field(default_factory=dict)
    # 选择提示而非 Agent 级硬拦截。空列表不会为候选打分增加实体要求。
    required_entities: list[str] = Field(default_factory=list)
    # 可选实体命中仅增加路由证据；空列表不参与打分。
    optional_entities: list[str] = Field(default_factory=list)
    output_schema: str
    # 当前 AgentCard 的私有工具严格白名单。空列表不暴露任何私有本地工具，
    # 不会回退为所有已注册工具。
    private_tools: list[str] = Field(default_factory=list)
    # 公共工具和 MCP 工具均需分别显式开启。
    public_tools_allowed: bool = False
    mcp_policy: MCPPolicy = Field(default_factory=MCPPolicy)
    # Skill 候选仅限此处声明的范围。空列表表示该 Agent 无可选 Skill。
    skills: list[str] = Field(default_factory=list)
    rag_namespaces: list[str] = Field(default_factory=list)
    memory_policy: MemoryPolicy = Field(default_factory=MemoryPolicy)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    access_policy: AgentAccessPolicy = Field(default_factory=AgentAccessPolicy)
    enabled: bool = True
    version: str

    @model_validator(mode="after")
    def validate_required_lists(self) -> "AgentCard":
        """Keep cards useful for selection instead of merely syntactically valid."""
        if not self.capabilities:
            raise ValueError(f"AgentCard {self.agent_name} must declare capabilities")
        if not self.supported_routes and self.supported_intents:
            first_intent = self.supported_intents[0]
            self.supported_routes = {first_intent: list(self.supported_sub_intents)}
        if self.supported_routes:
            normalized = self.normalized_supported_routes()
            self.supported_routes = normalized
            self.supported_intents = sorted(normalized) if not self.supported_intents else self.supported_intents
            if not self.supported_sub_intents:
                self.supported_sub_intents = sorted({sub for values in normalized.values() for sub in values})
        if not self.supported_routes:
            raise ValueError(f"AgentCard {self.agent_name} must declare supported_routes or supported_intents")
        return self

    def normalized_supported_routes(self) -> dict[str, list[str]]:
        """Return stable routes, converting legacy intent fields when needed."""
        routes = self.supported_routes or {}
        if not routes and self.supported_intents:
            routes = {self.supported_intents[0]: list(self.supported_sub_intents)}
        return {
            str(intent): sorted({str(sub_intent) for sub_intent in (sub_intents or []) if sub_intent})
            for intent, sub_intents in sorted(routes.items())
            if intent
        }


class AgentCandidate(BaseModel):
    """A scored candidate produced from AgentCard matching."""

    agent_name: str
    card: AgentCard
    score: float
    reason: str
    missing_entities: list[str] = Field(default_factory=list)
    matched_entities: list[str] = Field(default_factory=list)


class AgentSelectionResult(BaseModel):
    """Final selection decision used by the orchestrator."""

    selected_agent: str
    confidence: float
    reason: str
    required_context: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    candidates: list[AgentCandidate] = Field(default_factory=list)
    fallback: bool = False
    selection_method: Literal["rule", "llm_router", "fallback"] = "rule"
    need_clarification: bool = False
    clarification_question: str | None = None
    llm_status: str | None = None
    fallback_used: bool = False
    fallback_source: str | None = None
    fallback_reason: str | None = None
    decision_trace: dict[str, Any] = Field(default_factory=dict)
