from __future__ import annotations

"""AgentCard schemas used by orchestrator-side discovery and selection."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MemoryPolicy(BaseModel):
    """Controls how much conversation memory an agent receives."""

    use_short_summary: bool = True
    recent_turns: int = 5


class AgentCard(BaseModel):
    """Structured description of a sub agent discoverable by the main agent."""

    agent_name: str
    display_name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    supported_intents: list[str] = Field(default_factory=list)
    required_entities: list[str] = Field(default_factory=list)
    output_schema: str
    private_tools: list[str] = Field(default_factory=list)
    public_tools_allowed: bool = False
    mcp_tools: list[str] = Field(default_factory=list)
    mcp_tool_scopes: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    rag_namespaces: list[str] = Field(default_factory=list)
    memory_policy: MemoryPolicy = Field(default_factory=MemoryPolicy)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True
    version: str

    @model_validator(mode="after")
    def validate_required_lists(self) -> "AgentCard":
        """Keep cards useful for selection instead of merely syntactically valid."""
        if not self.capabilities:
            raise ValueError(f"AgentCard {self.agent_name} must declare capabilities")
        if not self.supported_intents:
            raise ValueError(f"AgentCard {self.agent_name} must declare supported_intents")
        return self


class AgentCandidate(BaseModel):
    """A scored candidate produced from AgentCard matching."""

    agent_name: str
    card: AgentCard
    score: float
    reason: str
    missing_entities: list[str] = Field(default_factory=list)


class AgentSelectionResult(BaseModel):
    """Final selection decision used by the orchestrator."""

    selected_agent: str
    confidence: float
    reason: str
    required_context: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    candidates: list[AgentCandidate] = Field(default_factory=list)
    fallback: bool = False
