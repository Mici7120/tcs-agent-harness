"""Decoupled ConfirmationBus inspired by Gemini CLI's confirmation-bus architecture."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from tcs_harness.types import ToolCall


@dataclass(slots=True)
class ConfirmationRequest:
    agent_name: str
    tool_call: ToolCall
    reason: str


@runtime_checkable
class ConfirmationBus(Protocol):
    async def request_confirmation(self, req: ConfirmationRequest) -> bool: ...


class AutoApproveBus:
    """Approves all ASK policy checks (useful in sandboxed CI or trusted automation)."""

    async def request_confirmation(self, req: ConfirmationRequest) -> bool:
        return True


class DenyAllBus:
    """Rejects all ASK policy checks (safe default for unattended non-sandboxed runs)."""

    async def request_confirmation(self, req: ConfirmationRequest) -> bool:
        return False


class CallbackConfirmationBus:
    """Delegates confirmation to an async or sync Python callback (ideal for Web UIs, Slack, tests)."""

    def __init__(self, handler: Callable[[ConfirmationRequest], bool | Awaitable[bool]]) -> None:
        self._handler = handler

    async def request_confirmation(self, req: ConfirmationRequest) -> bool:
        res = self._handler(req)
        if asyncio.iscoroutine(res) or isinstance(res, Awaitable):
            return bool(await res)
        return bool(res)


class RichCliConfirmationBus:
    """Interactive terminal prompt rendered via Rich."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    async def request_confirmation(self, req: ConfirmationRequest) -> bool:
        body = (
            f"[bold cyan]Agent:[/bold cyan] {req.agent_name}\n"
            f"[bold yellow]Tool:[/bold yellow] {req.tool_call.name}\n"
            f"[bold yellow]Args:[/bold yellow] {req.tool_call.arguments}\n"
            f"[dim]{req.reason}[/dim]"
        )
        self._console.print(Panel(body, title="Approval Required", border_style="yellow"))
        return await asyncio.to_thread(
            Confirm.ask, "Allow this action?", default=False, console=self._console
        )
