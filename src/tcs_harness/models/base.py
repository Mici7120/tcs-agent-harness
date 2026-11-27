"""Base ModelProvider protocol and testing/recording decorators (inspired by Gemini CLI's ContentGenerator)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from tcs_harness.types import Message, ModelResponse, TokenUsage, ToolSpec


@runtime_checkable
class ModelProvider(Protocol):
    """Unified interface across Google Gemini, Anthropic, OpenAI, and local models."""

    model_name: str

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        system_prompt: str = "",
        temperature: float = 0.1,
    ) -> ModelResponse: ...


class ScriptedModelProvider:
    """Deterministic scripted model provider for testing harness loops, policies, and stop gates."""

    def __init__(
        self,
        responses: list[ModelResponse] | Callable[[list[Message], list[ToolSpec] | None, str], ModelResponse],
        model_name: str = "scripted-mock",
    ) -> None:
        self.model_name = model_name
        self._responses = responses
        self.calls: list[dict[str, object]] = []
        self._idx = 0

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        system_prompt: str = "",
        temperature: float = 0.1,
    ) -> ModelResponse:
        self.calls.append(
            {
                "messages": [m.model_copy(deep=True) for m in messages],
                "tools": [t.name for t in (tools or [])],
                "system_prompt": system_prompt,
                "temperature": temperature,
            }
        )
        if callable(self._responses):
            return self._responses(messages, tools, system_prompt)
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return ModelResponse(
            content="[ScriptedModelProvider: exhausted scripted responses]",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            model=self.model_name,
        )


class RecordingModelProvider:
    """Decorator that records every LLM request/response pair to a JSONL file for auditing & evals."""

    def __init__(self, inner: ModelProvider, record_path: Path) -> None:
        self._inner = inner
        self.model_name = inner.model_name
        self._record_path = record_path
        self._record_path.parent.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        system_prompt: str = "",
        temperature: float = 0.1,
    ) -> ModelResponse:
        response = await self._inner.generate(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            temperature=temperature,
        )
        entry = {
            "model": self.model_name,
            "system_prompt_len": len(system_prompt),
            "messages": [m.model_dump() for m in messages],
            "tools": [t.name for t in (tools or [])],
            "response": response.model_dump(),
        }
        with self._record_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return response
