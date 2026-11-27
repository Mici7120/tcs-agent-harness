"""Tests for PolicyEngine, ConfirmationBus, and StopGate self-correction sensors."""

from __future__ import annotations

import sys
from pathlib import Path

from tcs_harness import (
    AgentRunner,
    ApprovalMode,
    AutoApproveBus,
    CallbackConfirmationBus,
    CommandStopGate,
    HarnessConfig,
    HookManager,
    ModelResponse,
    PolicyEngine,
    ScriptedModelProvider,
    ToolCall,
)
from tcs_harness.events import EventType


async def test_policy_denies_destructive_command_and_asks_confirmation(tmp_path: Path) -> None:
    asked_tools: list[str] = []

    def _on_confirm(req: object) -> bool:
        asked_tools.append(req.tool_call.name)  # type: ignore[attr-defined]
        return True

    scripted = ScriptedModelProvider(
        responses=[
            ModelResponse(
                tool_calls=[
                    ToolCall(id="bad", name="run_bash", arguments={"command": "rm -rf /"}),
                    ToolCall(id="ok", name="run_bash", arguments={"command": "echo hello-harness"}),
                ]
            ),
            ModelResponse(content="Policy checks verified."),
        ]
    )

    runner = AgentRunner(
        config=HarnessConfig(workspace=tmp_path),
        provider=scripted,
        policy=PolicyEngine(mode=ApprovalMode.AUTO_EDIT),
        confirmation_bus=CallbackConfirmationBus(_on_confirm),
    )
    res = await runner.run("Run two commands")

    assert res.completed is True
    assert asked_tools == ["run_bash"]  # Only the non-forbidden bash call reached ConfirmationBus
    tool_msgs = [m for m in res.messages if m.role.value == "tool"]
    assert "Policy denied" in tool_msgs[0].content
    assert "hello-harness" in tool_msgs[1].content


async def test_stop_gate_forces_agent_to_self_correct_before_finishing(tmp_path: Path) -> None:
    """Classic Harness Engineering test: agent claims completion while test fails -> StopGate rejects -> agent fixes code -> passes!"""
    (tmp_path / "test_math.py").write_text(
        "from math_mod import double\nassert double(4) == 8\n",
        encoding="utf-8",
    )

    scripted = ScriptedModelProvider(
        responses=[
            # Turn 1: Agent writes buggy implementation
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="w1",
                        name="write_file",
                        arguments={"path": "math_mod.py", "content": "def double(x):\n    return x * 3\n"},
                    )
                ]
            ),
            # Turn 2: Agent prematurely tries to stop without running tests!
            ModelResponse(content="All done! Implemented `double`."),
            # Turn 3: After receiving StopGate failure traceback, agent fixes the bug
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="e1",
                        name="edit_file",
                        arguments={
                            "path": "math_mod.py",
                            "old_text": "return x * 3",
                            "new_text": "return x * 2",
                        },
                    )
                ]
            ),
            # Turn 4: Agent finishes again -> StopGate now exits 0!
            ModelResponse(content="Fixed `double` and verified passing check."),
        ]
    )

    gate_cmd = f"{sys.executable} test_math.py"
    runner = AgentRunner(
        config=HarnessConfig(workspace=tmp_path, max_steps=8),
        provider=scripted,
        policy=PolicyEngine(mode=ApprovalMode.AUTO_EDIT),
        confirmation_bus=AutoApproveBus(),
        hooks=HookManager(stop_gates=[CommandStopGate(gate_cmd, name="unit-test-gate")]),
    )
    res = await runner.run("Implement math_mod.double")

    assert res.completed is True
    assert res.steps_used == 4
    gate_events = [e for e in res.events if e.type == EventType.STOP_GATE_CHECK]
    assert len(gate_events) == 2
    assert gate_events[0].data["passed"] is False
    assert gate_events[1].data["passed"] is True
    assert "return x * 2" in (tmp_path / "math_mod.py").read_text(encoding="utf-8")
