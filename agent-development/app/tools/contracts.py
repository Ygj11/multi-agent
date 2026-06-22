from __future__ import annotations

"""Minimal tool contract loading and validation."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


DEFAULT_TOOL_CONTRACTS_PATH = Path(__file__).with_name("tool_contracts.yaml")
DataClassification = Literal["public", "internal", "confidential", "sensitive"]


class RetryPolicy(BaseModel):
    """Minimal retry declaration.

    P4.4A deliberately keeps retry as a declaration only. Runtime retry
    execution is a later task.
    """

    max_attempts: int = 1

    @model_validator(mode="after")
    def validate_retry(self) -> "RetryPolicy":
        if self.max_attempts < 1:
            raise ValueError("retry.max_attempts must be >= 1")
        return self


class ToolContract(BaseModel):
    """Minimal execution contract attached to a ToolDefinition."""

    tool_name: str
    timeout_ms: int = 10000
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    result_schema: str | None = None
    approval_policy_id: str | None = None
    idempotency_key_fields: list[str] = Field(default_factory=list)
    data_classification: DataClassification = "internal"

    @model_validator(mode="after")
    def validate_contract(self) -> "ToolContract":
        if not self.tool_name.strip():
            raise ValueError("tool_name is required")
        if self.timeout_ms <= 0:
            raise ValueError(f"{self.tool_name}.timeout_ms must be > 0")
        return self


class ToolContractCatalog(BaseModel):
    """Loaded contract catalog with explicit tools plus MCP defaults."""

    version: str
    defaults: dict = Field(default_factory=dict)
    tools: dict[str, ToolContract] = Field(default_factory=dict)
    mcp_default: ToolContract | None = None

    @classmethod
    def load(cls, path: Path | str = DEFAULT_TOOL_CONTRACTS_PATH) -> "ToolContractCatalog":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("tool contract root must be a mapping")
        defaults = raw.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise ValueError("tool contract defaults must be a mapping")
        raw_tools = raw.get("tools") or {}
        if not isinstance(raw_tools, dict):
            raise ValueError("tool contract tools must be a mapping")
        tools = {
            str(tool_name): ToolContract(**{**defaults, **(definition or {}), "tool_name": str(tool_name)})
            for tool_name, definition in raw_tools.items()
        }
        raw_mcp_default = raw.get("mcp_default")
        mcp_default = None
        if isinstance(raw_mcp_default, dict):
            mcp_default = ToolContract(**{**defaults, **raw_mcp_default, "tool_name": "mcp.*"})
        return cls(
            version=str(raw.get("version") or "unknown"),
            defaults=defaults,
            tools=tools,
            mcp_default=mcp_default,
        )

    def contract_for(self, tool_name: str, *, source: str | None = None) -> ToolContract | None:
        """Return an explicit contract or the MCP default contract."""
        if tool_name in self.tools:
            return self.tools[tool_name]
        if source == "mcp" or tool_name.startswith("mcp."):
            return self._mcp_contract(tool_name)
        return None

    def explicit_tool_names(self) -> set[str]:
        return set(self.tools)

    def _mcp_contract(self, tool_name: str) -> ToolContract | None:
        if self.mcp_default is None:
            return None
        return self.mcp_default.model_copy(update={"tool_name": tool_name})

