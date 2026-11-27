"""ToolRegistry with error containment and smart large-output spill-to-disk truncation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tcs_harness.types import ToolCall, ToolResult, ToolSpec

ToolHandler = Callable[[dict[str, Any]], Awaitable[str] | str]


@dataclass(slots=True)
class RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    """Manages tool specifications, dispatches calls safely, and bounds output token bloat."""

    def __init__(
        self,
        max_output_chars: int = 12_000,
        spill_dir: Path | None = None,
    ) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self.max_output_chars = max_output_chars
        self.spill_dir = spill_dir

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get_spec(self, name: str) -> ToolSpec | None:
        reg = self._tools.get(name)
        return reg.spec if reg else None

    def list_specs(self, read_only_only: bool = False) -> list[ToolSpec]:
        specs = [t.spec for t in self._tools.values()]
        if read_only_only:
            return [s for s in specs if s.read_only]
        return specs

    def clone_subset(self, allowed_names: set[str] | None = None, read_only_only: bool = False) -> ToolRegistry:
        sub = ToolRegistry(max_output_chars=self.max_output_chars, spill_dir=self.spill_dir)
        for name, reg in self._tools.items():
            if allowed_names is not None and name not in allowed_names:
                continue
            if read_only_only and not reg.spec.read_only:
                continue
            sub.register(reg.spec, reg.handler)
        return sub

    def _bound_output(self, call_id: str, output: str) -> tuple[str, bool, str | None]:
        if len(output) <= self.max_output_chars:
            return output, False, None

        artifact_path: str | None = None
        if self.spill_dir is not None:
            self.spill_dir.mkdir(parents=True, exist_ok=True)
            out_file = self.spill_dir / f"{call_id}.txt"
            out_file.write_text(output, encoding="utf-8")
            artifact_path = str(out_file)

        half = self.max_output_chars // 2
        notice = (
            f"\n\n... [TRUNCATED {len(output) - self.max_output_chars} chars"
            + (f"; full output saved to {artifact_path}" if artifact_path else "")
            + "] ...\n\n"
        )
        bounded = output[:half] + notice + output[-half:]
        return bounded, True, artifact_path

    async def execute(self, call: ToolCall) -> ToolResult:
        reg = self._tools.get(call.name)
        if reg is None:
            available = ", ".join(sorted(self._tools)) or "(none)"
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                output=f"Error: Unknown tool '{call.name}'. Available tools: {available}",
                is_error=True,
            )

        try:
            raw = reg.handler(call.arguments)
            output_str = str(await raw) if asyncio.iscoroutine(raw) or isinstance(raw, Awaitable) else str(raw)
            bounded, truncated, artifact = self._bound_output(call.id, output_str)
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                output=bounded,
                is_error=False,
                truncated=truncated,
                artifact_path=artifact,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                output=f"Tool execution error ({type(exc).__name__}): {exc}",
                is_error=True,
            )
