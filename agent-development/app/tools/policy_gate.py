from __future__ import annotations

"""工具调用策略门。"""

from app.config.settings import Settings, get_settings
from app.observability.logger import log_event
from app.schemas.tool import ToolCall
from app.tools.http_tools import HTTPRequestTool
from app.tools.shell_exec_tool import ShellExecTool
from urllib.parse import urlparse


class PolicyGate:
    """在 ToolBroker 执行工具前做安全和权限判断。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """注入配置，便于测试 shell_exec 开关。"""
        self.settings = settings or get_settings()

    async def allow(self, call: ToolCall) -> tuple[bool, str | None]:
        """返回工具是否允许调用以及拒绝原因。"""
        if call.name in {"get_knowledge", "query_internal_log"}:
            self._log_checked(call, True, None)
            return True, None

        if call.name == "shell_exec":
            # shell_exec 默认拒绝，只有显式开启并且命令在 allowlist 中才放行。
            if not self.settings.enable_shell_exec:
                self._log_checked(call, False, "shell_exec is disabled by default")
                return False, "shell_exec is disabled by default"
            command = call.arguments.get("command")
            argv = ShellExecTool._normalize_command(command) if command is not None else []
            if not argv:
                self._log_checked(call, False, "shell_exec command is empty")
                return False, "shell_exec command is empty"
            if argv[0] not in ShellExecTool.allowlist:
                self._log_checked(call, False, f"shell_exec command is not allowlisted: {argv[0]}")
                return False, f"shell_exec command is not allowlisted: {argv[0]}"
            self._log_checked(call, True, None)
            return True, None

        if call.name in {"http_request", "mcp_http.call_tool"}:
            allowed, reason = self._allow_http_tool(call)
            self._log_checked(call, allowed, reason)
            return allowed, reason

        self._log_checked(call, False, f"tool is not allowed: {call.name}")
        return False, f"tool is not allowed: {call.name}"

    def _allow_http_tool(self, call: ToolCall) -> tuple[bool, str | None]:
        """校验 HTTP 类工具开关、方法、URL 协议和 host 白名单。"""
        if not self.settings.enable_http_tools:
            return False, "http tools are disabled by default"

        method = str(call.arguments.get("method", "POST" if call.name == "mcp_http.call_tool" else "")).upper()
        if call.name == "http_request" and method not in HTTPRequestTool.allowed_methods:
            return False, f"http method is not allowed: {method}"

        url = str(call.arguments.get("url") or call.arguments.get("base_url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False, "http tool url must use http or https"
        if not parsed.hostname:
            return False, "http tool url host is required"
        if self.settings.allowed_http_tool_hosts and parsed.hostname not in self.settings.allowed_http_tool_hosts:
            return False, f"http tool host is not allowlisted: {parsed.hostname}"

        timeout = float(call.arguments.get("timeout") or self.settings.http_tool_timeout)
        if timeout > self.settings.http_tool_timeout:
            return False, f"http tool timeout exceeds limit: {self.settings.http_tool_timeout}"
        return True, None

    def _log_checked(self, call: ToolCall, allowed: bool, reason: str | None) -> None:
        """记录策略判断结果。"""
        command = call.arguments.get("command")
        log_event(
            "policy_gate_checked",
            request_id=call.request_id,
            trace_id=call.trace_id,
            session_key=call.session_key,
            node="policy_gate",
            message="Policy gate checked",
            data={
                "tool_name": call.name,
                "allowed": allowed,
                "reason": reason,
                "shell_exec_enabled": self.settings.enable_shell_exec,
                "http_tools_enabled": self.settings.enable_http_tools,
                "command_preview": " ".join(ShellExecTool._normalize_command(command)) if command is not None else None,
            },
        )
