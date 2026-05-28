"""Restricted shell_exec and OpenAI provider default behavior tests."""

from pathlib import Path

from app.config.settings import Settings
from app.llm.opensdk_provider import OpenSDKLLMProvider
from app.tools.shell_exec_tool import ShellExecTool


async def test_shell_exec_disabled_by_default():
    tool = ShellExecTool(Path.cwd(), enabled=False)

    result = await tool(command=["echo", "hello"])

    assert result["success"] is False
    assert result["error"] == "shell_exec_disabled"


async def test_shell_exec_enabled_allows_allowlisted_command():
    tool = ShellExecTool(Path.cwd(), enabled=True)

    result = await tool(command=["echo", "hello"])

    assert result["success"] is True
    assert result["stdout"] == "hello\n"


async def test_shell_exec_enabled_rejects_non_allowlisted_command():
    tool = ShellExecTool(Path.cwd(), enabled=True)

    result = await tool(command=["rm", "-rf", "."])

    assert result["success"] is False
    assert "allowlisted" in result["error"]


def test_opensdk_provider_default_does_not_require_api_key():
    provider = OpenSDKLLMProvider(Settings(enable_real_llm=False, openai_api_key=None))
    assert provider.client is None
