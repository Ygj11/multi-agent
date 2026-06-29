from __future__ import annotations

"""Tool argument validation guard."""

from app.schemas.tool import ToolResult
from app.tools.error_codes import MISSING_REQUIRED_ARGUMENT


class ToolArgumentGuard:
    """校验 ToolDefinition 参数 schema 中声明的必填参数。

    缺参不会直接抛异常中断 Graph，而是返回 ToolResult observation 给 LLM。
    对需要工具事实的 Skill，BaseSubAgent 会在最终结果阶段防止无证据回答。
    """

    def __init__(self, registry) -> None:
        self.registry = registry

    def check_required(self, *, agent_name: str, tool_name: str, arguments: dict) -> ToolResult | None:
        required = self.registry.get_required_arguments(tool_name)
        missing = [name for name in required if name not in arguments or arguments.get(name) is None]
        if not missing:
            return None
        return ToolResult(
            name=tool_name,
            agent_name=agent_name,
            allowed=True,
            success=False,
            error=f"{MISSING_REQUIRED_ARGUMENT}:{','.join(missing)}",
            missing_required_arguments=missing,
        )
