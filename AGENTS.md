# AGENTS.md — `tcs-agent-harness`

## Map of the Repository
- `src/tcs_harness/types.py` & `events.py`: Core Pydantic models and immutable `HarnessEvent` stream.
- `src/tcs_harness/models/`: Multi-LLM Gateway (`GeminiProvider` via `google-genai`, `AnthropicProvider`, `OpenAICompatibleProvider` for OpenAI/Ollama/vLLM, `ScriptedModelProvider` & `RecordingModelProvider`).
- `src/tcs_harness/env/`: `LocalEnvironment` (workspace-confined stateless subprocesses) and `DockerSandboxEnvironment` (`docker exec` isolation).
- `src/tcs_harness/policy/`: `PolicyEngine` (`ALLOW`/`ASK`/`DENY`), `ConfirmationBus`, and `HookManager` (`CommandStopGate` sensors).
- `src/tcs_harness/context/`: Hierarchical `AGENTS.md` loader, progressive `SkillRegistry` (`SKILL.md`), `ContextCompactor`, and JSONL `SessionStore`.
- `src/tcs_harness/tools/` & `mcp/`: Minimal-core surgical tools + `StdioMcpClient` JSON-RPC 2.0 adapter.
- `src/tcs_harness/subagents/` & `runner.py`: `AgentRunner` turn loop, isolated subagents, and `ThreeStagePipeline` (`Planner -> Worker -> Evaluator`).

## Engineering Invariants ("Guides & Sensors")
1. **Minimal Core Toolset**: Keep built-in tools small and orthogonal; prefer adding domain capabilities via `skills/<name>/SKILL.md` or MCP servers.
2. **Never Bypass PolicyEngine**: Every tool call emitted by an LLM must flow through `HookManager.run_before_tool` -> `PolicyEngine.evaluate` -> `ConfirmationBus`.
3. **Deterministic Verification**: Always run `.venv/bin/pytest -q` and `.venv/bin/ruff check src tests` after modifying any module.
