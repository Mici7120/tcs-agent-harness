"""First-class Google Gemini provider built on the official google-genai SDK."""

from __future__ import annotations

import os
import uuid
from typing import Any

from google import genai
from google.genai import types

from tcs_harness.types import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolSpec


class GeminiProvider:
    """Google Gemini adapter supporting Gemini Developer API and Vertex AI."""

    def __init__(self, model_name: str = "gemini-2.5-flash", api_key: str | None = None) -> None:
        self.model_name = model_name
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
        if use_vertex:
            self._client = genai.Client(vertexai=True)
        elif resolved_key:
            self._client = genai.Client(api_key=resolved_key)
        else:
            # Deferred client init error only when called without credentials
            self._client = None

    def _convert_contents(self, messages: list[Message]) -> list[types.Content]:
        contents: list[types.Content] = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue
            if msg.role == Role.USER:
                contents.append(
                    types.Content(role="user", parts=[types.Part.from_text(text=msg.content)])
                )
            elif msg.role == Role.ASSISTANT:
                parts: list[types.Part] = []
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                for tc in msg.tool_calls:
                    parts.append(types.Part.from_function_call(name=tc.name, args=tc.arguments))
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
            elif msg.role == Role.TOOL:
                fn_name = msg.name or "tool"
                part = types.Part.from_function_response(
                    name=fn_name,
                    response={"result": msg.content},
                )
                # Merge consecutive tool responses into a single user/tool turn when required by Gemini
                if contents and contents[-1].role == "user" and contents[-1].parts and all(
                    p.function_response is not None for p in contents[-1].parts
                ):
                    contents[-1].parts.append(part)
                else:
                    contents.append(types.Content(role="user", parts=[part]))
        return contents

    def _convert_tools(self, tools: list[ToolSpec] | None) -> list[types.Tool] | None:
        if not tools:
            return None
        declarations = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters_json_schema=t.parameters,
            )
            for t in tools
        ]
        return [types.Tool(function_declarations=declarations)]

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        system_prompt: str = "",
        temperature: float = 0.1,
    ) -> ModelResponse:
        if self._client is None:
            raise RuntimeError(
                "Gemini credentials missing. Set GEMINI_API_KEY / GOOGLE_API_KEY or GOOGLE_GENAI_USE_VERTEXAI=true."
            )

        extra_sys = [m.content for m in messages if m.role == Role.SYSTEM and m.content]
        full_system = "\n\n".join(p for p in [system_prompt, *extra_sys] if p).strip()

        cfg_kwargs: dict[str, Any] = {"temperature": temperature}
        if full_system:
            cfg_kwargs["system_instruction"] = full_system
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            cfg_kwargs["tools"] = converted_tools

        config = types.GenerateContentConfig(**cfg_kwargs)
        contents = self._convert_contents(messages)

        raw = await self._client.aio.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        if raw.candidates and raw.candidates[0].content and raw.candidates[0].content.parts:
            for part in raw.candidates[0].content.parts:
                if part.text and not getattr(part, "thought", False):
                    text_parts.append(part.text)
                if part.function_call:
                    fc = part.function_call
                    call_id = getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:10]}"
                    tool_calls.append(
                        ToolCall(
                            id=call_id,
                            name=fc.name or "unknown_tool",
                            arguments=dict(fc.args) if fc.args else {},
                        )
                    )

        usage_meta = getattr(raw, "usage_metadata", None)
        usage = TokenUsage(
            input_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
        )

        return ModelResponse(
            content="\n".join(text_parts).strip(),
            tool_calls=tool_calls,
            usage=usage,
            model=self.model_name,
            stop_reason="tool_calls" if tool_calls else "stop",
        )
