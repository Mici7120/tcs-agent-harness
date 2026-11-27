"""Core AgentRunner executing the event-driven Turn loop, policies, compaction, and stop gates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from tcs_harness.context.agents_md import discover_agents_md
from tcs_harness.context.compaction import ContextCompactor
from tcs_harness.context.session import SessionStore
from tcs_harness.context.skills import SkillRegistry
from tcs_harness.env.base import ExecutionEnvironment
from tcs_harness.env.local import LocalEnvironment
from tcs_harness.events import EventType, HarnessEvent
from tcs_harness.models.base import ModelProvider
from tcs_harness.models.router import create_model_provider
from tcs_harness.policy.confirmation import ConfirmationBus, ConfirmationRequest, DenyAllBus
from tcs_harness.policy.engine import ApprovalMode, PolicyAction, PolicyEngine
from tcs_harness.policy.hooks import HookManager
from tcs_harness.tools.builtins import register_builtin_tools
from tcs_harness.tools.registry import ToolRegistry
from tcs_harness.types import HarnessConfig, Message, Role, TokenUsage, ToolResult

DEFAULT_BASE_PROMPT = """You are an autonomous software engineering & operations agent running inside `tcs-agent-harness`.
Operate methodically:
1. Inspect files and search context before making assumptions.
2. Prefer small, verifiable edits using `edit_file` or `write_file`.
3. Verify your work with tests/commands before declaring completion.
4. Respect workspace boundaries and policy decisions."""

EventListener = Callable[[HarnessEvent], None]


@dataclass(slots=True)
class RunResult:
    session_id: str
    final_output: str
    steps_used: int
    usage: TokenUsage
    events: list[HarnessEvent] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    completed: bool = True


class AgentRunner:
    """Orchestrates Model + Tools + Context + Policy + StopGates over an immutable Event stream."""

    def __init__(
        self,
        config: HarnessConfig | None = None,
        provider: ModelProvider | None = None,
        env: ExecutionEnvironment | None = None,
        tools: ToolRegistry | None = None,
        policy: PolicyEngine | None = None,
        confirmation_bus: ConfirmationBus | None = None,
        hooks: HookManager | None = None,
        skills: SkillRegistry | None = None,
        session_store: SessionStore | None = None,
        on_event: EventListener | None = None,
    ) -> None:
        self.config = config or HarnessConfig()
        self.workspace = self.config.workspace.resolve()
        self.provider = provider or create_model_provider(self.config.model)
        self.env = env or LocalEnvironment(self.workspace)

        tcs_state_dir = self.config.session_dir or (self.workspace / ".tcs")
        self.session_store = session_store or SessionStore(tcs_state_dir / "sessions")

        default_skill_dirs = [
            self.workspace / "skills",
            self.workspace / ".agents" / "skills",
            *self.config.skill_dirs,
        ]
        self.skills = skills or SkillRegistry(default_skill_dirs)

        if tools is not None:
            self.tools = tools
        else:
            self.tools = ToolRegistry(
                max_output_chars=self.config.max_tool_output_chars,
                spill_dir=tcs_state_dir / "tool_outputs",
            )
            register_builtin_tools(self.tools, self.env, self.skills)

        self.policy = policy or PolicyEngine(mode=ApprovalMode.AUTO_EDIT)
        self.confirmation_bus = confirmation_bus or DenyAllBus()
        self.hooks = hooks or HookManager()
        self.compactor = ContextCompactor(self.config.compaction)
        self._listeners: list[EventListener] = [on_event] if on_event else []
        self.total_usage = TokenUsage()

    def add_event_listener(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    def emit(self, event_type: EventType, step: int = 0, **data: object) -> HarnessEvent:
        evt = HarnessEvent(
            session_id=self.session_store.session_id,
            agent_name=self.config.agent_name,
            step=step,
            type=event_type,
            data=dict(data),
        )
        self.session_store.append_event(evt)
        for listener in self._listeners:
            listener(evt)
        return evt

    def build_system_prompt(self) -> str:
        sections = [
            DEFAULT_BASE_PROMPT,
            f"Workspace root: {self.workspace}",
        ]
        if self.config.load_agents_md:
            guides = discover_agents_md(self.workspace)
            if guides:
                sections.append("## Repository Instructions (AGENTS.md)\n" + guides)
        skill_catalog = self.skills.render_catalog_prompt()
        if skill_catalog:
            sections.append(skill_catalog)
        if self.config.system_prompt_extra:
            sections.append(self.config.system_prompt_extra.strip())
        return "\n\n".join(sections)

    async def run(
        self,
        prompt: str,
        history: list[Message] | None = None,
    ) -> RunResult:
        messages: list[Message] = list(history) if history else []
        messages.append(Message(role=Role.USER, content=prompt))
        system_prompt = self.build_system_prompt()
        run_events: list[HarnessEvent] = []

        def _record_local(evt: HarnessEvent) -> None:
            run_events.append(evt)

        self._listeners.append(_record_local)
        try:
            self.emit(
                EventType.RUN_STARTED,
                step=0,
                model=self.provider.model_name,
                prompt=prompt[:500],
            )

            for step in range(1, self.config.max_steps + 1):
                self.emit(EventType.STEP_STARTED, step=step)

                # 1. Context compaction check (Google ADK pattern)
                compaction = await self.compactor.maybe_compact(messages, self.provider)
                if compaction.compacted:
                    messages = compaction.messages
                    self.emit(
                        EventType.CONTEXT_COMPACTED,
                        step=step,
                        before_tokens=compaction.before_tokens,
                        after_tokens=compaction.after_tokens,
                        summarized_count=compaction.summarized_count,
                    )

                # 2. Model generation
                tool_specs = self.tools.list_specs(
                    read_only_only=(self.policy.mode == ApprovalMode.READ_ONLY)
                )
                response = await self.provider.generate(
                    messages=messages,
                    tools=tool_specs,
                    system_prompt=system_prompt,
                    temperature=self.config.temperature,
                )
                self.total_usage.add(response.usage)

                self.emit(
                    EventType.MODEL_RESPONSE,
                    step=step,
                    content=response.content[:1000],
                    tool_calls=[tc.name for tc in response.tool_calls],
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )

                messages.append(
                    Message(
                        role=Role.ASSISTANT,
                        content=response.content,
                        tool_calls=response.tool_calls,
                    )
                )

                # 3. No tool calls -> run StopGate verification sensors before finishing
                if not response.tool_calls:
                    gate_results = await self.hooks.run_stop_gates(response.content, self.env)
                    failed_gates = [g for g in gate_results if not g.passed]
                    for g in gate_results:
                        self.emit(
                            EventType.STOP_GATE_CHECK,
                            step=step,
                            gate=g.gate_name,
                            passed=g.passed,
                            feedback=g.feedback[:500],
                        )

                    if failed_gates:
                        feedback_body = "\n\n".join(g.feedback for g in failed_gates)
                        messages.append(
                            Message(
                                role=Role.USER,
                                content=f"[Harness Verification Sensor Failed]\n{feedback_body}",
                            )
                        )
                        self.session_store.save_messages(messages)
                        continue

                    self.session_store.save_messages(messages)
                    self.emit(
                        EventType.RUN_COMPLETED,
                        step=step,
                        total_tokens=self.total_usage.total_tokens,
                    )
                    return RunResult(
                        session_id=self.session_store.session_id,
                        final_output=response.content,
                        steps_used=step,
                        usage=self.total_usage.model_copy(),
                        events=run_events,
                        messages=messages,
                        completed=True,
                    )

                # 4. Execute each requested tool call through Hooks -> Policy -> ConfirmationBus -> Registry
                for raw_call in response.tool_calls:
                    self.emit(
                        EventType.TOOL_CALL_REQUESTED,
                        step=step,
                        tool=raw_call.name,
                        arguments=raw_call.arguments,
                    )
                    call = await self.hooks.run_before_tool(raw_call)
                    if call is None:
                        result = ToolResult(
                            tool_call_id=raw_call.id,
                            name=raw_call.name,
                            output="Blocked by before_tool hook.",
                            is_error=True,
                        )
                    else:
                        spec = self.tools.get_spec(call.name)
                        decision = self.policy.evaluate(call, spec)
                        approved = decision.action == PolicyAction.ALLOW

                        if decision.action == PolicyAction.ASK:
                            approved = await self.confirmation_bus.request_confirmation(
                                ConfirmationRequest(
                                    agent_name=self.config.agent_name,
                                    tool_call=call,
                                    reason=decision.reason,
                                )
                            )

                        self.emit(
                            EventType.POLICY_DECISION,
                            step=step,
                            tool=call.name,
                            action=decision.action.value,
                            approved=approved,
                            reason=decision.reason,
                        )

                        if not approved:
                            result = ToolResult(
                                tool_call_id=call.id,
                                name=call.name,
                                output=f"Policy denied tool '{call.name}': {decision.reason}",
                                is_error=True,
                            )
                        else:
                            result = await self.tools.execute(call)
                            result = await self.hooks.run_after_tool(call, result)

                    self.emit(
                        EventType.TOOL_RESULT,
                        step=step,
                        tool=result.name,
                        is_error=result.is_error,
                        truncated=result.truncated,
                        output_preview=result.output[:400],
                    )
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            tool_call_id=raw_call.id,
                            name=result.name,
                            content=result.output,
                        )
                    )

                self.session_store.save_messages(messages)

                if self.total_usage.total_tokens >= self.config.max_total_tokens:
                    msg = f"Stopped: token budget ({self.config.max_total_tokens}) reached."
                    self.emit(EventType.RUN_ERROR, step=step, reason=msg)
                    return RunResult(
                        session_id=self.session_store.session_id,
                        final_output=msg,
                        steps_used=step,
                        usage=self.total_usage.model_copy(),
                        events=run_events,
                        messages=messages,
                        completed=False,
                    )

            exhausted_msg = f"Stopped: max_steps ({self.config.max_steps}) reached without final stop."
            self.emit(EventType.RUN_ERROR, step=self.config.max_steps, reason=exhausted_msg)
            return RunResult(
                session_id=self.session_store.session_id,
                final_output=exhausted_msg,
                steps_used=self.config.max_steps,
                usage=self.total_usage.model_copy(),
                events=run_events,
                messages=messages,
                completed=False,
            )
        finally:
            self._listeners.remove(_record_local)
