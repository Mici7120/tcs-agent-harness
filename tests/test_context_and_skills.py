"""Tests for AGENTS.md discovery, SKILL.md progressive disclosure, and ContextCompactor."""

from __future__ import annotations

from pathlib import Path

from tcs_harness import (
    AgentRunner,
    CompactionConfig,
    HarnessConfig,
    Message,
    ModelResponse,
    Role,
    ScriptedModelProvider,
    ToolCall,
)
from tcs_harness.context import ContextCompactor, SkillRegistry, discover_agents_md


def test_agents_md_and_progressive_skills_loading(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("# Root Guide\nAlways run pytest.", encoding="utf-8")
    sub = tmp_path / "services" / "api"
    sub.mkdir(parents=True)
    (sub / "AGENTS.md").write_text("# API Guide\nUse FastAPI.", encoding="utf-8")

    discovered = discover_agents_md(sub)
    assert "Root Guide" in discovered
    assert "API Guide" in discovered
    assert discovered.index("Root Guide") < discovered.index("API Guide")

    skill_dir = tmp_path / "skills" / "deploy-check"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: deploy-check\ndescription: Pre-deployment checklist.\n---\nStep 1: Verify migrations.\nStep 2: Smoke test healthz.\n",
        encoding="utf-8",
    )
    (skill_dir / "checklist.txt").write_text("item1", encoding="utf-8")

    registry = SkillRegistry([tmp_path / "skills"])
    catalog = registry.render_catalog_prompt()
    assert "deploy-check" in catalog
    assert "Pre-deployment checklist." in catalog
    assert "Step 1: Verify migrations." not in catalog  # Progressive disclosure: body NOT in catalog!

    activated = registry.render_activated_skill("deploy-check")
    assert "Step 1: Verify migrations." in activated
    assert "checklist.txt" in activated


async def test_context_compactor_preserves_goal_and_tool_pairs(tmp_path: Path) -> None:
    compactor = ContextCompactor(
        CompactionConfig(
            enabled=True,
            token_threshold=150,
            tail_retention_messages=3,
            use_llm_summarizer=True,
        )
    )
    summarizer_mock = ScriptedModelProvider(
        responses=[ModelResponse(content="Summary: inspected alpha.py and beta.py.")]
    )

    messages = [
        Message(role=Role.USER, content="Original critical goal: refactor authentication."),
        Message(role=Role.ASSISTANT, content="Checking files " + ("A" * 400)),
        Message(role=Role.USER, content="Proceed " + ("B" * 400)),
        Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="tc_tail", name="read_file", arguments={"path": "auth.py"})],
        ),
        Message(role=Role.TOOL, tool_call_id="tc_tail", name="read_file", content="def login(): pass"),
        Message(role=Role.USER, content="Now update login()."),
    ]

    outcome = await compactor.maybe_compact(messages, summarizer_mock)
    assert outcome.compacted is True
    assert outcome.after_tokens < outcome.before_tokens
    assert outcome.messages[0].content == "Original critical goal: refactor authentication."
    assert "Context Compaction Summary" in outcome.messages[1].content
    # Ensure tool call and its matching tool result were NOT split apart
    roles = [m.role for m in outcome.messages[2:]]
    assert roles == [Role.ASSISTANT, Role.TOOL, Role.USER]


async def test_agent_runner_activates_skill_on_demand(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "sec-audit"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: sec-audit\ndescription: Security audit workflow.\n---\nSECRET_RULE_42: Check JWT alg!=none.",
        encoding="utf-8",
    )

    scripted = ScriptedModelProvider(
        responses=[
            ModelResponse(
                tool_calls=[
                    ToolCall(id="sk1", name="activate_skill", arguments={"skill_name": "sec-audit"})
                ]
            ),
            ModelResponse(content="Applied SECRET_RULE_42."),
        ]
    )
    runner = AgentRunner(config=HarnessConfig(workspace=tmp_path), provider=scripted)
    res = await runner.run("Audit JWT auth")

    assert res.completed is True
    tool_msgs = [m for m in res.messages if m.role == Role.TOOL]
    assert "SECRET_RULE_42" in tool_msgs[0].content
