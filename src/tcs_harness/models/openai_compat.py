"""OpenAI-compatible provider supporting OpenAI, Ollama, vLLM, DeepSeek, and OpenRouter."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from tcs_harness.types import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolSpec


class OpenAICompatibleProvider:
    """Unified Chat Completions adapter for OpenAI and local/compatible servers."""

    def __init__(
        self,
        model_name: str = "gpt-4.1",
        api_key: str | None = None,
        base_url: str | None = None,
        require_api_key: bool = True,
    ) -> None:
        self.model_name = model_name
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        ).rstrip("/")
        self._require_api_key = require_api_key

    def _format_messages(
        self, messages: list[Message], system_prompt: str
    ) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        extra_sys = [m.content for m in messages if m.role == Role.SYSTEM and m.content]
        full_system = "\n\n".join(p for p in [system_prompt, *extra_sys] if p).strip()
        if full_system:
            formatted.append({"role": "system", "content": full_system})

        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue
            if msg.role == Role.USER:
                formatted.append({"role": "user", "content": msg.content})
            elif msg.role == Role.ASSISTANT:
                entry: dict[str, Any] = {"role": "assistant", "content": msg.content or None}
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                formatted.append(entry)
            elif msg.role == Role.TOOL:
                formatted.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id or "",
                        "name": msg.name or "tool",
                        "content": msg.content,
                    }
                )
        return formatted

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        system_prompt: str = "",
        temperature: float = 0.1,
    ) -> ModelResponse:
        if self._require_api_key and not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")

        payload: dict[str, Any] = {
            "model": self.model_name,
            "temperature": temperature,
            "messages": self._format_messages(messages, system_prompt),
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions", headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""

        tool_calls: list[ToolCall] = []
        for raw_tc in message.get("tool_calls") or []:
            fn = raw_tc.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                parsed_args = {"_raw": raw_args}
            tool_calls.append(
                ToolCall(
                    id=raw_tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=parsed_args,
                )
            )

        usage_raw = data.get("usage") or {}
        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=usage_raw.get("prompt_tokens", 0),
                output_tokens=usage_raw.get("completion_tokens", 0),
            ),
            model=data.get("model", self.model_name),
            stop_reason=choice.get("finish_reason") or "stop",
        )
