"""Tests for AgentRunner core loop, built-in tools, workspace confinement, truncation, and JSONL sessions."""

from __future__ import annotations

from pathlib import Path

from tcs_harness import (
    AgentRunner,
    HarnessConfig,
    ModelResponse,
    RecordingModelProvider,
    ScriptedModelProvider,
    TokenUsage,
    ToolCall,
)
from tcs_harness.events import EventType


async def test_core_loop_write_edit_read_and_jsonl_session(tmp_path: Path) -> None:
    scripted = ScriptedModelProvider(
        responses=[
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="write_file",
                        arguments={"path": "calc.py", "content": "def add(a, b):\n    return a - b\n"},
                    )
                ],
                usage=TokenUsage(input_tokens=40, output_tokens=20),
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="edit_file",
                        arguments={
                            "path": "calc.py",
                            "old_text": "return a - b",
                            "new_text": "return a + b",
                        },
                    )
                ],
                usage=TokenUsage(input_tokens=60, output_tokens=20),
            ),
            ModelResponse(
                content="Fixed `calc.py` addition logic.",
                usage=TokenUsage(input_tokens=70, output_tokens=15),
            ),
        ]
    )
    record_file = tmp_path / "recorded_calls.jsonl"
    provider = RecordingModelProvider(scripted, record_file)

    runner = AgentRunner(
        config=HarnessConfig(workspace=tmp_path, max_steps=10),
        provider=provider,
    )
    result = await runner.run("Create and fix calc.py")

    assert result.completed is True
    assert result.steps_used == 3
    assert result.usage.total_tokens == 225
    assert "return a + b" in (tmp_path / "calc.py").read_text(encoding="utf-8")
    assert record_file.is_file()
    assert len(record_file.read_text(encoding="utf-8").splitlines()) == 3

    saved_events = runner.session_store.load_events()
    assert any(e.type == EventType.RUN_COMPLETED for e in saved_events)
    assert len(runner.session_store.load_messages()) == 6


async def test_workspace_boundary_confinement_and_output_truncation(tmp_path: Path) -> None:
    huge_file = tmp_path / "big.log"
    huge_file.write_text("X" * 5000, encoding="utf-8")

    scripted = ScriptedModelProvider(
        responses=[
            ModelResponse(
                tool_calls=[
                    ToolCall(id="escape", name="read_file", arguments={"path": "../etc/passwd"}),
                    ToolCall(id="big", name="read_file", arguments={"path": "big.log"}),
                ]
            ),
            ModelResponse(content="Handled boundary error and truncated output."),
        ]
    )
    runner = AgentRunner(
        config=HarnessConfig(workspace=tmp_path, max_tool_output_chars=400),
        provider=scripted,
    )
    res = await runner.run("Test boundary and truncation")

    assert res.completed is True
    tool_msgs = [m for m in res.messages if m.role.value == "tool"]
    assert len(tool_msgs) == 2
    assert "outside workspace" in tool_msgs[0].content
    assert "TRUNCATED" in tool_msgs[1].content
