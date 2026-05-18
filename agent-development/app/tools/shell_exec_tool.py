from __future__ import annotations

"""受限 shell_exec 工具。

第一阶段只暴露非常小的 allowlist，并由 PolicyGate 控制是否可调用。
"""

from pathlib import Path
from typing import Any


class ShellExecTool:
    """安全受限的 shell_exec 实现。"""

    allowlist = {"echo", "pwd", "ls"}

    def __init__(self, project_root: Path) -> None:
        """将执行范围固定在项目根目录。"""
        self.project_root = project_root.resolve()

    async def __call__(self, command: list[str] | str, timeout: float = 5, **kwargs: Any) -> dict[str, Any]:
        """执行 allowlist 中的命令。

        为了跨平台和安全，本 MVP 不启动系统 shell，也不执行任意二进制。
        """
        argv = self._normalize_command(command)
        if not argv:
            raise ValueError("command must not be empty")
        if argv[0] not in self.allowlist:
            raise PermissionError(f"command is not allowlisted: {argv[0]}")

        # Keep the first-stage MVP deterministic and cross-platform while preserving
        # the security boundary: no shell=True, allowlist only, project-root scoped.
        _safe_timeout = min(float(timeout), 5.0)
        if argv[0] == "echo":
            stdout = " ".join(argv[1:]) + ("\n" if len(argv) > 1 else "")
        elif argv[0] == "pwd":
            stdout = f"{self.project_root}\n"
        else:
            stdout = "\n".join(sorted(path.name for path in self.project_root.iterdir())) + "\n"

        return {"returncode": 0, "stdout": stdout, "stderr": ""}

    @staticmethod
    def _normalize_command(command: list[str] | str) -> list[str]:
        """把字符串或列表命令标准化为 argv。"""
        if isinstance(command, str):
            return command.strip().split()
        return [str(part) for part in command]
