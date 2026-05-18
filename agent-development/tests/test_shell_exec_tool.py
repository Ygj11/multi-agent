"""受限 shell_exec 和 OpenAI Provider 默认行为测试。"""

from pathlib import Path

from app.config.settings import Settings
from app.llm.openai_provider import OpenAICompatibleLLMProvider
from app.schemas.tool import ToolCall
from app.tools.broker import ToolBroker
from app.tools.policy_gate import PolicyGate
from app.tools.registry import ToolRegistry
from app.tools.shell_exec_tool import ShellExecTool


async def test_shell_exec_disabled_by_default():
    """shell_exec 默认应被 PolicyGate 拒绝。"""
    registry = ToolRegistry()
    registry.register("shell_exec", ShellExecTool(Path.cwd()))
    broker = ToolBroker(registry=registry, policy_gate=PolicyGate(Settings(enable_shell_exec=False)))

    result = await broker.call(ToolCall(name="shell_exec", arguments={"command": ["echo", "hello"]}))

    assert result.success is False
    assert result.allowed is False
    assert "disabled" in result.error


async def test_shell_exec_enabled_allows_allowlisted_command():
    """开启后只允许 allowlist 中的命令。"""
    registry = ToolRegistry()
    registry.register("shell_exec", ShellExecTool(Path.cwd()))
    broker = ToolBroker(registry=registry, policy_gate=PolicyGate(Settings(enable_shell_exec=True)))

    result = await broker.call(ToolCall(name="shell_exec", arguments={"command": ["echo", "hello"]}))

    assert result.success is True
    assert result.allowed is True
    assert result.result["stdout"] == "hello\n"


async def test_shell_exec_enabled_rejects_non_allowlisted_command():
    """开启后仍应拒绝 rm 等非 allowlist 命令。"""
    registry = ToolRegistry()
    registry.register("shell_exec", ShellExecTool(Path.cwd()))
    broker = ToolBroker(registry=registry, policy_gate=PolicyGate(Settings(enable_shell_exec=True)))

    result = await broker.call(ToolCall(name="shell_exec", arguments={"command": ["rm", "-rf", "."]}))

    assert result.success is False
    assert result.allowed is False
    assert "allowlisted" in result.error


def test_openai_provider_default_does_not_require_api_key():
    """真实 LLM 默认不启用，缺少 API key 不应影响测试。"""
    provider = OpenAICompatibleLLMProvider(Settings(enable_real_llm=False, openai_api_key=None))
    assert provider.client is None
