from __future__ import annotations

"""Result schema registry for tool observations."""

from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError


class AnyDictResult(RootModel[dict[str, Any]]):
    """A dict-shaped result."""


class TextResult(RootModel[str]):
    """A text result."""


class CalculatorResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    success: bool
    result: Any = None
    error: str | None = None


class CurrentTimeResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    utc: str


class PosAPIResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    success: bool
    path: str
    url: str | None = None
    request_payload: dict[str, Any]
    response: Any = None
    status_code: int | None = None
    error: str | None = None
    duration_ms: int | None = None


class HTTPToolResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    success: bool
    error: str | None = None


class ShellExecResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    success: bool
    error: str | None = None


RESULT_SCHEMA_REGISTRY: dict[str, type[BaseModel] | type[RootModel]] = {
    "AnyDictResult": AnyDictResult,
    "TextResult": TextResult,
    "CalculatorResult": CalculatorResult,
    "CurrentTimeResult": CurrentTimeResult,
    "PosAPIResult": PosAPIResult,
    "HTTPToolResult": HTTPToolResult,
    "ShellExecResult": ShellExecResult,
}


def validate_tool_result_schema(schema_name: str | None, value: Any) -> str | None:
    """Return validation error detail or None when the value matches."""
    if not schema_name:
        return None
    schema = RESULT_SCHEMA_REGISTRY.get(schema_name)
    if schema is None:
        return f"unknown_result_schema:{schema_name}"
    try:
        schema.model_validate(value)
    except ValidationError as exc:
        return str(exc)
    return None
