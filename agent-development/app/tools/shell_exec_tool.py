from __future__ import annotations

"""Restricted shell_exec tool."""

from pathlib import Path
from typing import Any


class ShellExecTool:
    """Safe deterministic shell_exec replacement for the local MVP."""

    allowlist = {"echo", "pwd", "ls"}

    def __init__(self, project_root: Path, *, enabled: bool = False) -> None:
        self.project_root = project_root.resolve()
        self.enabled = enabled

    async def __call__(self, command: list[str] | str, timeout: float = 5, **kwargs: Any) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "error": "shell_exec_disabled"}
        argv = self._normalize_command(command)
        if not argv:
            return {"success": False, "error": "command must not be empty"}
        if argv[0] not in self.allowlist:
            return {"success": False, "error": f"command is not allowlisted: {argv[0]}"}

        _safe_timeout = min(float(timeout), 5.0)
        if argv[0] == "echo":
            stdout = " ".join(argv[1:]) + ("\n" if len(argv) > 1 else "")
        elif argv[0] == "pwd":
            stdout = f"{self.project_root}\n"
        else:
            stdout = "\n".join(sorted(path.name for path in self.project_root.iterdir())) + "\n"

        return {"success": True, "returncode": 0, "stdout": stdout, "stderr": "", "timeout": _safe_timeout}

    @staticmethod
    def _normalize_command(command: list[str] | str) -> list[str]:
        if isinstance(command, str):
            return command.strip().split()
        return [str(part) for part in command]
