"""Provider router resolving 'provider:model' strings into concrete ModelProvider instances."""

from __future__ import annotations

import os

from tcs_harness.models.anthropic import AnthropicProvider
from tcs_harness.models.base import ModelProvider, ScriptedModelProvider
from tcs_harness.models.gemini import GeminiProvider
from tcs_harness.models.openai_compat import OpenAICompatibleProvider
from tcs_harness.types import ModelResponse, TokenUsage


def create_model_provider(model_spec: str) -> ModelProvider:
    """Resolve specs like 'gemini:gemini-2.5-flash', 'anthropic:claude-sonnet-4-5', 'openai:gpt-4.1', 'ollama:qwen2.5-coder'."""
    if ":" in model_spec:
        provider_prefix, model_name = model_spec.split(":", 1)
        provider_prefix = provider_prefix.lower().strip()
    else:
        model_name = model_spec.strip()
        if model_name.startswith("gemini"):
            provider_prefix = "gemini"
        elif model_name.startswith("claude"):
            provider_prefix = "anthropic"
        else:
            provider_prefix = "openai"

    if provider_prefix in ("gemini", "google"):
        return GeminiProvider(model_name=model_name)
    if provider_prefix == "anthropic":
        return AnthropicProvider(model_name=model_name)
    if provider_prefix == "openai":
        return OpenAICompatibleProvider(model_name=model_name)
    if provider_prefix in ("ollama", "local"):
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        return OpenAICompatibleProvider(
            model_name=model_name,
            api_key="ollama",
            base_url=base_url,
            require_api_key=False,
        )
    if provider_prefix == "mock":
        return ScriptedModelProvider(
            responses=lambda msgs, _tools, _sys: ModelResponse(
                content=f"[Mock response from {model_name}] Received {len(msgs)} message(s).",
                usage=TokenUsage(input_tokens=32, output_tokens=16),
                model=model_name,
            ),
            model_name=model_name,
        )

    raise ValueError(
        f"Unknown model provider prefix '{provider_prefix}' in '{model_spec}'. "
        "Supported prefixes: gemini, anthropic, openai, ollama, mock."
    )
