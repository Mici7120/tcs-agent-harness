"""Lightweight async Model Context Protocol (MCP) JSON-RPC 2.0 stdio client."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Self

from tcs_harness.tools.registry import ToolRegistry
from tcs_harness.types import ToolSpec


class StdioMcpClient:
    """Connects to any MCP-compliant stdio server and bridges its tools into ToolRegistry."""

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        server_name: str = "mcp",
    ) -> None:
        self.command = command
        self.env = env
        self.server_name = server_name
        self._proc: asyncio.subprocess.Process | None = None
        self._req_id = 0
        self._lock = asyncio.Lock()

    async def connect(self) -> dict[str, Any]:
        self._proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.env,
        )
        init_res = await self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "tcs-agent-harness", "version": "0.1.0"},
            },
        )
        await self.notify("notifications/initialized", {})
        return init_res

    async def close(self) -> None:
        if self._proc is None:
            return
        if self._proc.stdin and not self._proc.stdin.is_closing():
            self._proc.stdin.close()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=2.0)
        except TimeoutError:
            self._proc.kill()
            await self._proc.wait()
        self._proc = None

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self._proc or not self._proc.stdin:
            raise RuntimeError("MCP client is not connected.")
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise RuntimeError("MCP client is not connected.")

        async with self._lock:
            self._req_id += 1
            req_id = self._req_id
            payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                payload["params"] = params
            self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self._proc.stdin.drain()

            while True:
                line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=30.0)
                if not line:
                    raise RuntimeError(f"MCP server '{self.server_name}' closed stdout unexpectedly.")
                msg = json.loads(line.decode("utf-8"))
                if msg.get("id") == req_id:
                    if "error" in msg:
                        raise RuntimeError(f"MCP error: {msg['error']}")
                    return dict(msg.get("result") or {})

    async def list_tools(self) -> list[dict[str, Any]]:
        res = await self.request("tools/list", {})
        return list(res.get("tools") or [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        res = await self.request("tools/call", {"name": name, "arguments": arguments})
        parts: list[str] = []
        for item in res.get("content") or []:
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(json.dumps(item))
        if res.get("isError"):
            raise RuntimeError("\n".join(parts) or "MCP tool returned error")
        return "\n".join(parts)

    async def register_into(self, registry: ToolRegistry, prefix: bool = True) -> list[str]:
        tools = await self.list_tools()
        registered_names: list[str] = []
        for raw_tool in tools:
            orig_name = str(raw_tool["name"])
            exposed_name = f"{self.server_name}__{orig_name}" if prefix else orig_name
            schema = raw_tool.get("inputSchema") or {"type": "object", "properties": {}}
            annotations = raw_tool.get("annotations") or {}
            read_only = bool(annotations.get("readOnlyHint", False))

            async def _invoke(args: dict[str, Any], _target: str = orig_name) -> str:
                return await self.call_tool(_target, args)

            registry.register(
                ToolSpec(
                    name=exposed_name,
                    description=str(raw_tool.get("description") or f"MCP tool {orig_name}"),
                    parameters=schema,
                    read_only=read_only,
                ),
                _invoke,
            )
            registered_names.append(exposed_name)
        return registered_names
