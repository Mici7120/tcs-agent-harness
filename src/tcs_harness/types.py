"""Core data structures for messages, tool specifications, model responses, and harness configuration."""

from __future__ import annotations

import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """Represents a structured tool invocation emitted by the LLM."""

    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:10]}")
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result returned by the harness after executing (or blocking) a tool call."""

    tool_call_id: str
    name: str
    output: str
    is_error: bool = False
    truncated: bool = False
    artifact_path: str | None = None


class Message(BaseModel):
    """Unified provider-agnostic conversation turn message."""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def estimate_tokens(self) -> int:
        """Fast heuristic (~4 chars/token) used by the ContextCompactor before model calls."""
        payload = self.content
        if self.tool_calls:
            payload += " " + " ".join(f"{tc.name}:{tc.arguments}" for tc in self.tool_calls)
        return max(1, len(payload) // 4)


class ToolSpec(BaseModel):
    """JSON-Schema specification of a tool exposed to the model."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    read_only: bool = False


class TokenUsage(BaseModel):
    """Token accounting across turns and subagents."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: TokenUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


class ModelResponse(BaseModel):
    """Standardized response returned by any ModelProvider."""

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str = ""
    stop_reason: str = "stop"


class CompactionConfig(BaseModel):
    """Token-threshold and tail-retention context compaction config (inspired by Google ADK)."""

    enabled: bool = True
    token_threshold: int = 24_000
    tail_retention_messages: int = 6
    use_llm_summarizer: bool = True


class HarnessConfig(BaseModel):
    """Top-level runtime settings for an AgentRunner instance."""

    model: str = "gemini:gemini-2.5-flash"
    workspace: Path = Field(default_factory=Path.cwd)
    max_steps: int = 25
    max_total_tokens: int = 250_000
    max_tool_output_chars: int = 12_000
    temperature: float = 0.1
    load_agents_md: bool = True
    skill_dirs: list[Path] = Field(default_factory=list)
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    session_dir: Path | None = None
    agent_name: str = "root"
    system_prompt_extra: str = ""
