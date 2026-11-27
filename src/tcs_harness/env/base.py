"""ExecutionEnvironment protocol decoupling tools from local subprocess vs Docker sandbox."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def combined_output(self) -> str:
        parts: list[str] = []
        if self.stdout:
            parts.append(self.stdout.rstrip())
        if self.stderr:
            parts.append(f"[stderr]\n{self.stderr.rstrip()}")
        if self.timed_out:
            parts.append("[timed out]")
        return "\n".join(parts) if parts else "(no output)"


@runtime_checkable
class ExecutionEnvironment(Protocol):
    workspace: Path

    def resolve_path(self, relative_or_abs: str) -> Path: ...

    def read_text(self, path: str) -> str: ...

    def write_text(self, path: str, content: str) -> Path: ...

    async def run_command(self, command: str, timeout_sec: float = 30.0) -> CommandResult: ...
