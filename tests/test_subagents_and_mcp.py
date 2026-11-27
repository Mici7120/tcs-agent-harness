"""Tests for isolated-context Subagents, ThreeStagePipeline, and live stdio MCP client integration."""

from __future__ import annotations

import sys
from pathlib import Path

from tcs_harness import (
    AgentRunner,
    ApprovalMode,
    AutoApproveBus,
    HarnessConfig,
    ModelResponse,
    PolicyEngine,
    ScriptedModelProvider,
    StdioMcpClient,
    ThreeStagePipeline,
    TokenUsage,
    ToolCall,
    register_subagent_tool,
)
from tcs_harness.events import EventType


async def test_isolated_subagent_delegation_and_read_only_enforcement(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text("PORT = 8080\n", encoding="utf-8")

    parent_provider = ScriptedModelProvider(
        responses=[
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="sub1",
                        name="delegate_subagent",
                        arguments={"role": "researcher", "task": "Find configured PORT in service.py"},
                    )
                ],
                usage=TokenUsage(input_tokens=30, output_tokens=15),
            ),
            ModelResponse(
                content="The researcher confirmed PORT = 8080.",
                usage=TokenUsage(input_tokens=50, output_tokens=10),
            ),
        ]
    )
    child_provider = ScriptedModelProvider(
        responses=[
            ModelResponse(
                tool_calls=[
                    ToolCall(id="r1", name="read_file", arguments={"path": "service.py"}),
                ],
                usage=TokenUsage(input_tokens=20, output_tokens=10),
            ),
            ModelResponse(
                content="Found `PORT = 8080` in `service.py:1`.",
                usage=TokenUsage(input_tokens=25, output_tokens=12),
            ),
        ]
    )

    runner = AgentRunner(config=HarnessConfig(workspace=tmp_path), provider=parent_provider)
    register_subagent_tool(runner, provider_override=child_provider)

    res = await runner.run("What port does service.py use?")
    assert res.completed is True
    assert "8080" in res.final_output
    # Parent usage (95) + child usage (67) rolled up cleanly
    assert res.usage.total_tokens == 172
    assert any(e.type == EventType.SUBAGENT_COMPLETED for e in res.events)
    # Parent message history stays compact (only 4 messages: user, assistant call, subagent summary, final)
    assert len(res.messages) == 4


async def test_three_stage_planner_worker_evaluator_pipeline(tmp_path: Path) -> None:
    providers = {
        "planner": ScriptedModelProvider([ModelResponse(content="1. Create feature.py\n2. Verify output")]),
        "worker": ScriptedModelProvider(
            [
                ModelResponse(content="Initial draft written."),
                ModelResponse(content="Addressed evaluator feedback and added edge case check."),
            ]
        ),
        "evaluator": ScriptedModelProvider(
            [
                ModelResponse(content="Missing null check. VERDICT: FAIL"),
                ModelResponse(content="All checks verified cleanly. VERDICT: PASS"),
            ]
        ),
    }

    def _factory(role: str, mode: ApprovalMode) -> AgentRunner:
        return AgentRunner(
            config=HarnessConfig(workspace=tmp_path, agent_name=role),
            provider=providers[role],
            policy=PolicyEngine(mode=mode),
            confirmation_bus=AutoApproveBus(),
        )

    pipeline = ThreeStagePipeline(_factory, max_eval_rounds=3)
    outcome = await pipeline.execute("Implement feature.py")

    assert outcome.passed is True
    assert outcome.rounds == 2
    assert "VERDICT: PASS" in outcome.evaluation


async def test_stdio_mcp_client_integration_with_agent_runner(tmp_path: Path) -> None:
    fixture_script = Path(__file__).parent / "fixtures" / "mock_mcp_server.py"
    async with StdioMcpClient([sys.executable, str(fixture_script)], server_name="crypto") as mcp:
        scripted = ScriptedModelProvider(
            responses=[
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            id="m1",
                            name="crypto__sha256_hex",
                            arguments={"text": "tcs-harness"},
                        )
                    ]
                ),
                ModelResponse(content="Computed digest via MCP server."),
            ]
        )
        runner = AgentRunner(config=HarnessConfig(workspace=tmp_path), provider=scripted)
        registered = await mcp.register_into(runner.tools)
        assert registered == ["crypto__sha256_hex"]

        res = await runner.run("Hash 'tcs-harness' using MCP")
        assert res.completed is True
        tool_msgs = [m for m in res.messages if m.role.value == "tool"]
        assert "digest=cf69e71320b6227a" in tool_msgs[0].content
