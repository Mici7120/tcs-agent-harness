"""Lifecycle Hooks & Stop Gates ('Sensors' in Harness Engineering)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from tcs_harness.env.base import ExecutionEnvironment
from tcs_harness.types import ToolCall, ToolResult


@dataclass(slots=True)
class StopGateResult:
    passed: bool
    feedback: str = ""
    gate_name: str = "stop_gate"


BeforeToolHook = Callable[[ToolCall], Awaitable[ToolCall | None] | ToolCall | None]
AfterToolHook = Callable[[ToolCall, ToolResult], Awaitable[ToolResult] | ToolResult]
StopGateHook = Callable[[str, ExecutionEnvironment], Awaitable[StopGateResult] | StopGateResult]


class CommandStopGate:
    """Runs a verification shell command (e.g. pytest, ruff, mypy) before allowing the agent to finish."""

    def __init__(self, command: str, name: str | None = None, timeout_sec: float = 60.0) -> None:
        self.command = command
        self.name = name or f"cmd:{command}"
        self.timeout_sec = timeout_sec

    async def __call__(self, _final_answer: str, env: ExecutionEnvironment) -> StopGateResult:
        res = await env.run_command(self.command, timeout_sec=self.timeout_sec)
        if res.exit_code == 0:
            return StopGateResult(passed=True, gate_name=self.name)
        return StopGateResult(
            passed=False,
            gate_name=self.name,
            feedback=(
                f"Stop gate '{self.name}' failed (exit code {res.exit_code}). "
                f"Fix the issues and verify again before completing:\n{res.combined_output[:4000]}"
            ),
        )


class HookManager:
    """Coordinates PreToolUse, PostToolUse, and StopGate verification sensors."""

    def __init__(
        self,
        before_tool: list[BeforeToolHook] | None = None,
        after_tool: list[AfterToolHook] | None = None,
        stop_gates: list[StopGateHook] | None = None,
    ) -> None:
        self.before_tool: list[BeforeToolHook] = list(before_tool or [])
        self.after_tool: list[AfterToolHook] = list(after_tool or [])
        self.stop_gates: list[StopGateHook] = list(stop_gates or [])

    async def run_before_tool(self, call: ToolCall) -> ToolCall | None:
        current: ToolCall | None = call
        for hook in self.before_tool:
            if current is None:
                return None
            out = hook(current)
            current = await out if asyncio.iscoroutine(out) or isinstance(out, Awaitable) else out
        return current

    async def run_after_tool(self, call: ToolCall, result: ToolResult) -> ToolResult:
        current = result
        for hook in self.after_tool:
            out = hook(call, current)
            current = await out if asyncio.iscoroutine(out) or isinstance(out, Awaitable) else out
        return current

    async def run_stop_gates(
        self, final_answer: str, env: ExecutionEnvironment
    ) -> list[StopGateResult]:
        results: list[StopGateResult] = []
        for gate in self.stop_gates:
            out = gate(final_answer, env)
            res = await out if asyncio.iscoroutine(out) or isinstance(out, Awaitable) else out
            results.append(res)
        return results
