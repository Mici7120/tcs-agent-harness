"""Stateless local workspace execution environment with strict workspace path confinement."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from tcs_harness.env.base import CommandResult


class WorkspaceBoundaryError(PermissionError):
    """Raised when a tool attempts to access paths outside the configured workspace root."""


class LocalEnvironment:
    """Executes file operations and stateless subprocess commands confined to workspace."""

    def __init__(self, workspace: Path, extra_env: dict[str, str] | None = None) -> None:
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._extra_env = extra_env or {}

    def resolve_path(self, relative_or_abs: str) -> Path:
        candidate = Path(relative_or_abs)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.workspace / candidate).resolve()
        )
        if resolved != self.workspace and self.workspace not in resolved.parents:
            raise WorkspaceBoundaryError(
                f"Path '{relative_or_abs}' resolves outside workspace '{self.workspace}'."
            )
        return resolved

    def read_text(self, path: str) -> str:
        target = self.resolve_path(path)
        return target.read_text(encoding="utf-8", errors="replace")

    def write_text(self, path: str, content: str) -> Path:
        target = self.resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        if target.suffix == ".py":
            pycache = target.parent / "__pycache__"
            if pycache.is_dir():
                for pyc in pycache.glob(f"{target.stem}.*.pyc"):
                    pyc.unlink(missing_ok=True)
        return target

    async def run_command(self, command: str, timeout_sec: float = 30.0) -> CommandResult:
        env = {**os.environ, "PAGER": "cat", "PYTHONDONTWRITEBYTECODE": "1", **self._extra_env}
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            return CommandResult(
                exit_code=proc.returncode or 0,
                stdout=stdout_b.decode("utf-8", errors="replace"),
                stderr=stderr_b.decode("utf-8", errors="replace"),
                timed_out=False,
            )
        except TimeoutError:
            proc.kill()
            stdout_b, stderr_b = await proc.communicate()
            return CommandResult(
                exit_code=124,
                stdout=stdout_b.decode("utf-8", errors="replace"),
                stderr=stderr_b.decode("utf-8", errors="replace"),
                timed_out=True,
            )
