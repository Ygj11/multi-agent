from __future__ import annotations

"""Normalize LLM tool_calls from supported provider formats."""

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class NormalizedToolCall:
    """Provider-independent tool call."""

    id: str | None
    name: str
    arguments: dict[str, Any]
    raw: Any
    error: str | None = None


def normalize_tool_calls(raw_tool_calls: list[Any]) -> list[NormalizedToolCall]:
    """Normalize a list of tool calls or return per-call errors."""
    return [normalize_tool_call(tool_call) for tool_call in raw_tool_calls]


def normalize_tool_call(tool_call: Any) -> NormalizedToolCall:
    name = extract_tool_name(tool_call)
    args = extract_tool_arguments(tool_call)
    call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
    if isinstance(name, ToolCallParseError):
        return NormalizedToolCall(id=call_id, name="", arguments={}, raw=tool_call, error=name.message)
    if isinstance(args, ToolCallParseError):
        return NormalizedToolCall(id=call_id, name=name, arguments={}, raw=tool_call, error=args.message)
    return NormalizedToolCall(id=call_id, name=name, arguments=args, raw=tool_call)


class ToolCallParseError:
    """Simple value object used to keep parsing errors explicit."""

    def __init__(self, message: str) -> None:
        self.message = message

    def __repr__(self) -> str:
        return f"ToolCallParseError({self.message!r})"


def extract_tool_name(tool_call: Any) -> str | ToolCallParseError:
    """Extract tool name from OpenAI or internal simplified formats."""
    if not isinstance(tool_call, dict):
        return ToolCallParseError("tool_call_must_be_object")
    function = tool_call.get("function")
    if isinstance(function, dict) and function.get("name"):
        return str(function["name"])
    if tool_call.get("name"):
        return str(tool_call["name"])
    return ToolCallParseError("tool_name_missing")


def extract_tool_arguments(tool_call: Any) -> dict[str, Any] | ToolCallParseError:
    """Extract and JSON-decode tool arguments."""
    if not isinstance(tool_call, dict):
        return ToolCallParseError("tool_call_must_be_object")
    raw_arguments: Any = None
    function = tool_call.get("function")
    if isinstance(function, dict) and "arguments" in function:
        raw_arguments = function.get("arguments")
    elif "arguments" in tool_call:
        raw_arguments = tool_call.get("arguments")

    if raw_arguments is None or raw_arguments == "":
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            return ToolCallParseError(f"tool_arguments_invalid_json: {exc.msg}")
        if not isinstance(parsed, dict):
            return ToolCallParseError("tool_arguments_must_be_object")
        return parsed
    return ToolCallParseError("tool_arguments_unsupported_type")

