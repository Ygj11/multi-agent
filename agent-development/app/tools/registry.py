from __future__ import annotations

"""工具注册表。"""

from collections.abc import Awaitable, Callable
from typing import Any


ToolCallable = Callable[..., Awaitable[Any]]


class ToolRegistry:
    """保存工具名称到异步可调用对象的映射。"""

    def __init__(self) -> None:
        """初始化空工具目录。"""
        self._tools: dict[str, ToolCallable] = {}

    def register(self, name: str, tool: ToolCallable) -> None:
        """注册一个工具实现。"""
        self._tools[name] = tool

    def get(self, name: str) -> ToolCallable | None:
        """按名称查找工具。"""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """列出已注册工具名称。"""
        return sorted(self._tools)
