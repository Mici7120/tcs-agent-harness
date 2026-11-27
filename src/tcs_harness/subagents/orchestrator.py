"""Isolated-context subagents and Anthropic-style Planner -> Worker -> Evaluator pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tcs_harness.events import EventType
from tcs_harness.models.base import ModelProvider
from tcs_harness.policy.engine import ApprovalMode, PolicyEngine
from tcs_harness.runner import AgentRunner, RunResult
from tcs_harness.types import HarnessConfig, TokenUsage, ToolSpec


@dataclass(slots=True)
class SubagentProfile:
    role: str
    description: str
    system_prompt: str
    approval_mode: ApprovalMode
    max_steps: int = 12


DEFAULT_SUBAGENT_PROFILES: dict[str, SubagentProfile] = {
    "researcher": SubagentProfile(
        role="researcher",
        description="Read-only codebase explorer. Summarizes relevant files, symbols, and architecture.",
        system_prompt=(
            "You are a Read-Only Codebase Researcher subagent. Inspect files and search symbols, "
            "then return a concise, well-cited summary with exact file paths and line numbers."
        ),
        approval_mode=ApprovalMode.READ_ONLY,
        max_steps=10,
    ),
    "planner": SubagentProfile(
        role="planner",
        description="Read-only software architect. Produces an actionable step-by-step implementation & test plan.",
        system_prompt=(
            "You are a Lead Software Planner subagent. Do NOT edit files. Inspect the workspace and "
            "produce a concrete, ordered implementation plan specifying files to touch, edge cases, "
            "and exact verification commands."
        ),
        approval_mode=ApprovalMode.READ_ONLY,
        max_steps=10,
    ),
    "worker": SubagentProfile(
        role="worker",
        description="Implementation subagent that executes edits and runs verification commands in an isolated context.",
        system_prompt=(
            "You are an Implementation Worker subagent. Execute the assigned task cleanly, "
            "run relevant tests, and report exact changes made and verification output."
        ),
        approval_mode=ApprovalMode.AUTO_EDIT,
        max_steps=18,
    ),
    "evaluator": SubagentProfile(
        role="evaluator",
        description="Independent skeptic reviewer that audits changes and runs checks. Outputs VERDICT: PASS or VERDICT: FAIL.",
        system_prompt=(
            "You are an Independent Evaluator subagent. Do NOT trust self-reported claims. "
            "Inspect modified files and run tests if available. End your response with either "
            "'VERDICT: PASS' or 'VERDICT: FAIL' followed by concrete actionable findings."
        ),
        approval_mode=ApprovalMode.READ_ONLY,
        max_steps=10,
    ),
}


def register_subagent_tool(
    parent: AgentRunner,
    profiles: dict[str, SubagentProfile] | None = None,
    provider_override: ModelProvider | None = None,
) -> None:
    """Registers `delegate_subagent` on a parent AgentRunner so it can spawn isolated subagents."""
    available_profiles = profiles or DEFAULT_SUBAGENT_PROFILES
    roles_list = sorted(available_profiles.keys())

    async def handle_delegate(args: dict[str, Any]) -> str:
        role = str(args["role"]).strip().lower()
        task = str(args["task"]).strip()
        if role not in available_profiles:
            raise ValueError(f"Unknown subagent role '{role}'. Available roles: {', '.join(roles_list)}")

        profile = available_profiles[role]
        parent.emit(EventType.SUBAGENT_STARTED, role=role, task=task[:300])

        # Exclude delegate_subagent from child tools to prevent unbounded recursion
        allowed = {
            s.name for s in parent.tools.list_specs() if s.name != "delegate_subagent"
        }
        child_tools = parent.tools.clone_subset(
            allowed_names=allowed,
            read_only_only=(profile.approval_mode == ApprovalMode.READ_ONLY),
        )
        child_cfg = HarnessConfig(
            model=parent.config.model,
            workspace=parent.workspace,
            max_steps=profile.max_steps,
            max_total_tokens=parent.config.max_total_tokens // 2,
            max_tool_output_chars=parent.config.max_tool_output_chars,
            temperature=parent.config.temperature,
            load_agents_md=parent.config.load_agents_md,
            compaction=parent.config.compaction,
            session_dir=parent.config.session_dir,
            agent_name=f"subagent:{role}",
            system_prompt_extra=profile.system_prompt,
        )
        child_runner = AgentRunner(
            config=child_cfg,
            provider=provider_override or parent.provider,
            env=parent.env,
            tools=child_tools,
            policy=PolicyEngine(mode=profile.approval_mode),
            confirmation_bus=parent.confirmation_bus,
            skills=parent.skills,
            session_store=parent.session_store,
        )
        res = await child_runner.run(task)
        parent.total_usage.add(res.usage)
        parent.emit(
            EventType.SUBAGENT_COMPLETED,
            role=role,
            steps=res.steps_used,
            tokens=res.usage.total_tokens,
            completed=res.completed,
        )
        return f"[Subagent '{role}' report ({res.steps_used} steps)]\n{res.final_output}"

    parent.tools.register(
        ToolSpec(
            name="delegate_subagent",
            description=(
                "Spawn an isolated-context subagent to research, plan, implement, or evaluate a focused subtask. "
                f"Available roles: {', '.join(roles_list)}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": roles_list,
                        "description": "Specialized subagent role.",
                    },
                    "task": {
                        "type": "string",
                        "description": "Clear, self-contained instructions and acceptance criteria for the subagent.",
                    },
                },
                "required": ["role", "task"],
            },
            read_only=False,
        ),
        handle_delegate,
    )


@dataclass(slots=True)
class PipelineOutcome:
    passed: bool
    plan: str
    worker_output: str
    evaluation: str
    rounds: int
    usage: TokenUsage


class ThreeStagePipeline:
    """Anthropic's 3-Agent Harness Pattern: Planner -> Worker (context reset) -> Evaluator loop."""

    def __init__(
        self,
        base_runner_factory: Any,
        max_eval_rounds: int = 2,
    ) -> None:
        self._factory = base_runner_factory
        self.max_eval_rounds = max_eval_rounds

    async def execute(self, goal: str) -> PipelineOutcome:
        total_usage = TokenUsage()

        # Stage 1: Planner (fresh read-only context)
        planner: AgentRunner = self._factory("planner", ApprovalMode.READ_ONLY)
        plan_res: RunResult = await planner.run(
            f"Create a concise step-by-step engineering plan for this goal:\n\n{goal}"
        )
        total_usage.add(plan_res.usage)
        plan_text = plan_res.final_output

        feedback = ""
        worker_out = ""
        eval_out = ""

        for round_idx in range(1, self.max_eval_rounds + 1):
            # Stage 2: Worker / Generator (fresh context reset carrying only goal + plan + prior eval feedback)
            worker: AgentRunner = self._factory("worker", ApprovalMode.AUTONOMOUS)
            worker_prompt = f"## Goal\n{goal}\n\n## Approved Plan\n{plan_text}"
            if feedback:
                worker_prompt += f"\n\n## Evaluator Feedback from Previous Round\n{feedback}"
            w_res: RunResult = await worker.run(worker_prompt)
            total_usage.add(w_res.usage)
            worker_out = w_res.final_output

            # Stage 3: Independent Evaluator (fresh context so it grades objectively, not generously!)
            evaluator: AgentRunner = self._factory("evaluator", ApprovalMode.AUTONOMOUS)
            eval_prompt = (
                f"Audit whether the workspace implementation satisfies the goal.\n\n"
                f"## Goal\n{goal}\n\n## Worker Summary\n{worker_out}\n\n"
                f"Inspect actual files/tests and conclude with 'VERDICT: PASS' or 'VERDICT: FAIL'."
            )
            e_res: RunResult = await evaluator.run(eval_prompt)
            total_usage.add(e_res.usage)
            eval_out = e_res.final_output

            if "VERDICT: PASS" in eval_out.upper():
                return PipelineOutcome(
                    passed=True,
                    plan=plan_text,
                    worker_output=worker_out,
                    evaluation=eval_out,
                    rounds=round_idx,
                    usage=total_usage,
                )
            feedback = eval_out

        return PipelineOutcome(
            passed=False,
            plan=plan_text,
            worker_output=worker_out,
            evaluation=eval_out,
            rounds=self.max_eval_rounds,
            usage=total_usage,
        )
