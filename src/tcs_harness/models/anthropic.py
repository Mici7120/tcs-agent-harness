"""Native Anthropic Messages API provider via httpx."""

from __future__ import annotations

import os
from typing import Any

import httpx

from tcs_harness.types import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolSpec


class AnthropicProvider:
    """Adapter for Claude models using Anthropic's /v1/messages endpoint."""

    def __init__(
        self,
        model_name: str = "claude-sonnet-4-5",
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 8192,
    ) -> None:
        self.model_name = model_name
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._base_url = (
            base_url or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
        ).rstrip("/")
        self._max_tokens = max_tokens

    def _format_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue
            if msg.role == Role.USER:
                formatted.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                blocks: list[dict[str, Any]] = []
                if msg.content:
                    blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                if blocks:
                    formatted.append({"role": "assistant", "content": blocks})
            elif msg.role == Role.TOOL:
                block = {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": msg.content,
                }
                if (
                    formatted
                    and formatted[-1]["role"] == "user"
                    and isinstance(formatted[-1]["content"], list)
                ):
                    formatted[-1]["content"].append(block)
                else:
                    formatted.append({"role": "user", "content": [block]})
        return formatted

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        system_prompt: str = "",
        temperature: float = 0.1,
    ) -> ModelResponse:
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")

        extra_sys = [m.content for m in messages if m.role == Role.SYSTEM and m.content]
        full_system = "\n\n".join(p for p in [system_prompt, *extra_sys] if p).strip()

        payload: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self._max_tokens,
            "temperature": temperature,
            "messages": self._format_messages(messages),
        }
        if full_system:
            payload["system"] = full_system
        if tools:
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self._base_url}/v1/messages", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input", {}) or {},
                    )
                )

        usage_raw = data.get("usage", {})
        return ModelResponse(
            content="\n".join(text_parts).strip(),
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=usage_raw.get("input_tokens", 0),
                output_tokens=usage_raw.get("output_tokens", 0),
            ),
            model=data.get("model", self.model_name),
            stop_reason=data.get("stop_reason", "stop"),
        )
