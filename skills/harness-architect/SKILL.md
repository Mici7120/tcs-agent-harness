---
name: harness-architect
description: Extend tcs-agent-harness with custom tools, PolicyRules, StopGate verification sensors, subagent profiles, or MCP servers.
---
# Harness Architect Skill

Follow this checklist whenever adding capabilities to `tcs-agent-harness`:

## 1. Adding a Custom Tool
Register a `ToolSpec` and handler on `runner.tools`:
- Set `read_only=True` ONLY if the tool has zero side effects on files, processes, or external state.
- Raise standard Python exceptions on invalid input; `ToolRegistry` automatically converts them into `ToolResult(is_error=True)` so the model self-corrects.

## 2. Adding a Verification Sensor (`StopGate`)
Prefer deterministic sensors over longer prompts:
- Use `CommandStopGate("pytest -q")` in `HookManager(stop_gates=[...])` so the agent cannot stop while tests are failing.

## 3. Adding Policy Rules
Add `PolicyRule(tool_name="run_bash", command_regex=r"...", action=PolicyAction.DENY, reason="...")` to `PolicyEngine(custom_rules=[...])`.
