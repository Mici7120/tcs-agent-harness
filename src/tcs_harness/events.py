"""Immutable event stream protocol inspired by Google ADK and OpenHands."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    STEP_STARTED = "step_started"
    MODEL_RESPONSE = "model_response"
    TOOL_CALL_REQUESTED = "tool_call_requested"
    POLICY_DECISION = "policy_decision"
    TOOL_RESULT = "tool_result"
    CONTEXT_COMPACTED = "context_compacted"
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_COMPLETED = "subagent_completed"
    STOP_GATE_CHECK = "stop_gate_check"
    RUN_COMPLETED = "run_completed"
    RUN_ERROR = "run_error"


class HarnessEvent(BaseModel):
    """Single immutable event emitted by the AgentRunner and persisted to JSONL sessions."""

    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    session_id: str
    agent_name: str = "root"
    step: int = 0
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
