"""Rich CLI for tcs-agent-harness (`tcs run`, `tcs chat`, `tcs pipeline`, `tcs skills`, `tcs sessions`, `tcs doctor`)."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from tcs_harness.context.session import SessionStore
from tcs_harness.context.skills import SkillRegistry
from tcs_harness.env.docker_sandbox import DockerSandboxEnvironment
from tcs_harness.env.local import LocalEnvironment
from tcs_harness.events import EventType, HarnessEvent
from tcs_harness.mcp.client import StdioMcpClient
from tcs_harness.models.router import create_model_provider
from tcs_harness.policy.confirmation import AutoApproveBus, RichCliConfirmationBus
from tcs_harness.policy.engine import ApprovalMode, PolicyEngine
from tcs_harness.policy.hooks import CommandStopGate, HookManager
from tcs_harness.runner import AgentRunner
from tcs_harness.subagents.orchestrator import (
    DEFAULT_SUBAGENT_PROFILES,
    ThreeStagePipeline,
    register_subagent_tool,
)
from tcs_harness.types import HarnessConfig


def _make_event_printer(console: Console) -> object:
    def _on_event(evt: HarnessEvent) -> None:
        if evt.type == EventType.TOOL_CALL_REQUESTED:
            console.print(
                f"  [cyan]→ [{evt.agent_name}] tool[/cyan] [bold]{evt.data.get('tool')}[/bold] {evt.data.get('arguments')}"
            )
        elif evt.type == EventType.TOOL_RESULT:
            status = "[red]ERR[/red]" if evt.data.get("is_error") else "[green]OK[/green]"
            console.print(f"  [dim]← {evt.data.get('tool')}[/dim] {status}")
        elif evt.type == EventType.CONTEXT_COMPACTED:
            console.print(
                f"  [magenta]⚡ Context compacted:[/magenta] {evt.data.get('before_tokens')} → {evt.data.get('after_tokens')} est. tokens"
            )
        elif evt.type == EventType.STOP_GATE_CHECK:
            passed = evt.data.get("passed")
            badge = "[green]PASS[/green]" if passed else "[red]FAIL (re-entering loop)[/red]"
            console.print(f"  [yellow]⛨ StopGate[/yellow] {evt.data.get('gate')}: {badge}")
        elif evt.type == EventType.SUBAGENT_STARTED:
            console.print(f"  [blue]⊕ Spawning subagent[/blue] [bold]{evt.data.get('role')}[/bold]")

    return _on_event


async def _cmd_run(args: argparse.Namespace, console: Console) -> int:
    workspace = Path(args.workspace).resolve()
    mode = ApprovalMode(args.mode)
    cfg = HarnessConfig(
        model=args.model,
        workspace=workspace,
        max_steps=args.max_steps,
    )

    env_cm = (
        DockerSandboxEnvironment(workspace=workspace, image=args.docker_image)
        if args.docker
        else None
    )
    env = env_cm if env_cm is not None else LocalEnvironment(workspace)

    hooks = HookManager(
        stop_gates=[CommandStopGate(cmd) for cmd in (args.verify_cmd or [])]
    )
    confirmation_bus = AutoApproveBus() if args.yes else RichCliConfirmationBus(console)

    mcp_clients: list[StdioMcpClient] = []
    try:
        if env_cm is not None:
            await env_cm.start()

        runner = AgentRunner(
            config=cfg,
            env=env,
            policy=PolicyEngine(mode=mode),
            confirmation_bus=confirmation_bus,
            hooks=hooks,
            on_event=_make_event_printer(console),  # type: ignore[arg-type]
        )
        if not args.no_subagents:
            register_subagent_tool(runner)

        for mcp_cmd in args.mcp_stdio or []:
            client = StdioMcpClient(mcp_cmd.split(), server_name="mcp")
            await client.connect()
            await client.register_into(runner.tools)
            mcp_clients.append(client)

        res = await runner.run(args.prompt)
        console.print(
            Panel(
                Markdown(res.final_output or "(empty output)"),
                title=f"Session {res.session_id} • {res.steps_used} steps • {res.usage.total_tokens} tokens",
                border_style="green" if res.completed else "yellow",
            )
        )
        return 0 if res.completed else 1
    finally:
        for c in mcp_clients:
            await c.close()
        if env_cm is not None:
            await env_cm.stop()


async def _cmd_chat(args: argparse.Namespace, console: Console) -> int:
    workspace = Path(args.workspace).resolve()
    cfg = HarnessConfig(model=args.model, workspace=workspace, max_steps=args.max_steps)
    runner = AgentRunner(
        config=cfg,
        policy=PolicyEngine(mode=ApprovalMode(args.mode)),
        confirmation_bus=RichCliConfirmationBus(console),
        on_event=_make_event_printer(console),  # type: ignore[arg-type]
    )
    register_subagent_tool(runner)

    console.print(
        Panel(
            f"[bold]tcs-agent-harness[/bold] interactive mode\n"
            f"Model: [cyan]{args.model}[/cyan] | Workspace: [green]{workspace}[/green]\n"
            f"Type [bold]/exit[/bold] or Ctrl-D to quit.",
            border_style="cyan",
        )
    )
    history = []
    while True:
        try:
            user_input = await asyncio.to_thread(console.input, "\n[bold cyan]tcs>[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye!")
            return 0
        prompt = user_input.strip()
        if not prompt:
            continue
        if prompt in ("/exit", "/quit"):
            return 0
        res = await runner.run(prompt, history=history)
        history = res.messages
        console.print(Markdown(res.final_output or ""))


async def _cmd_pipeline(args: argparse.Namespace, console: Console) -> int:
    workspace = Path(args.workspace).resolve()
    provider = create_model_provider(args.model)

    def _factory(role: str, mode: ApprovalMode) -> AgentRunner:
        prof = DEFAULT_SUBAGENT_PROFILES[role]
        cfg = HarnessConfig(
            model=args.model,
            workspace=workspace,
            max_steps=prof.max_steps,
            agent_name=f"pipeline:{role}",
            system_prompt_extra=prof.system_prompt,
        )
        return AgentRunner(
            config=cfg,
            provider=provider,
            policy=PolicyEngine(mode=mode),
            confirmation_bus=AutoApproveBus() if args.yes else RichCliConfirmationBus(console),
            on_event=_make_event_printer(console),  # type: ignore[arg-type]
        )

    pipeline = ThreeStagePipeline(_factory, max_eval_rounds=args.rounds)
    outcome = await pipeline.execute(args.goal)
    console.print(Panel(Markdown(outcome.plan), title="1. Planner Output", border_style="blue"))
    console.print(Panel(Markdown(outcome.evaluation), title=f"3. Evaluator ({'PASS' if outcome.passed else 'FAIL'})", border_style="green" if outcome.passed else "red"))
    return 0 if outcome.passed else 1


def _cmd_skills(args: argparse.Namespace, console: Console) -> int:
    workspace = Path(args.workspace).resolve()
    reg = SkillRegistry([workspace / "skills", workspace / ".agents" / "skills"])
    table = Table(title=f"Discovered Skills in {workspace}")
    table.add_column("Skill Name", style="cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("Path", style="dim")
    for s in reg.list_skills():
        table.add_row(s.name, s.description, str(s.skill_file.relative_to(workspace)))
    console.print(table)
    return 0


def _cmd_sessions(args: argparse.Namespace, console: Console) -> int:
    workspace = Path(args.workspace).resolve()
    sessions = SessionStore.list_sessions(workspace / ".tcs" / "sessions")
    table = Table(title="Recorded Harness Sessions")
    table.add_column("Session ID", style="cyan")
    table.add_column("Events", justify="right")
    for sid in sessions[:20]:
        store = SessionStore(workspace / ".tcs" / "sessions", session_id=sid)
        table.add_row(sid, str(len(store.load_events())))
    console.print(table)
    return 0


def _cmd_doctor(console: Console) -> int:
    table = Table(title="tcs-agent-harness Environment Diagnostics")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    checks = [
        ("GEMINI_API_KEY / GOOGLE_API_KEY", bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")), "Google Gemini native provider"),
        ("ANTHROPIC_API_KEY", bool(os.environ.get("ANTHROPIC_API_KEY")), "Anthropic Messages API provider"),
        ("OPENAI_API_KEY", bool(os.environ.get("OPENAI_API_KEY")), "OpenAI Chat Completions provider"),
        ("Docker CLI", shutil.which("docker") is not None, shutil.which("docker") or "Not found"),
    ]
    for name, ok, detail in checks:
        badge = "[green]READY[/green]" if ok else "[yellow]OPTIONAL / UNSET[/yellow]"
        table.add_row(name, badge, detail)
    console.print(table)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tcs", description="tcs-agent-harness CLI")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_run = sub.add_parser("run", help="Execute a single autonomous agent task")
    p_run.add_argument("prompt", help="Task instructions for the agent")
    p_run.add_argument("-m", "--model", default="gemini:gemini-2.5-flash", help="Model spec (e.g. gemini:gemini-2.5-pro, anthropic:claude-sonnet-4-5, ollama:qwen2.5-coder)")
    p_run.add_argument("-w", "--workspace", default=".", help="Workspace directory")
    p_run.add_argument("--mode", default="auto_edit", choices=[m.value for m in ApprovalMode])
    p_run.add_argument("--max-steps", type=int, default=25)
    p_run.add_argument("-y", "--yes", action="store_true", help="Auto-approve confirmation prompts")
    p_run.add_argument("--verify-cmd", action="append", help="StopGate shell command that must exit 0 before completion (repeatable)")
    p_run.add_argument("--docker", action="store_true", help="Execute bash commands inside an isolated Docker sandbox container")
    p_run.add_argument("--docker-image", default="python:3.12-slim")
    p_run.add_argument("--no-subagents", action="store_true")
    p_run.add_argument("--mcp-stdio", action="append", help="Attach stdio MCP server command (repeatable)")

    p_chat = sub.add_parser("chat", help="Interactive multi-turn terminal session")
    p_chat.add_argument("-m", "--model", default="gemini:gemini-2.5-flash")
    p_chat.add_argument("-w", "--workspace", default=".")
    p_chat.add_argument("--mode", default="auto_edit", choices=[m.value for m in ApprovalMode])
    p_chat.add_argument("--max-steps", type=int, default=25)

    p_pipe = sub.add_parser("pipeline", help="Run Planner -> Worker -> Evaluator 3-stage pipeline")
    p_pipe.add_argument("goal", help="Engineering objective")
    p_pipe.add_argument("-m", "--model", default="gemini:gemini-2.5-flash")
    p_pipe.add_argument("-w", "--workspace", default=".")
    p_pipe.add_argument("--rounds", type=int, default=2)
    p_pipe.add_argument("-y", "--yes", action="store_true")

    p_skills = sub.add_parser("skills", help="List discovered SKILL.md modules")
    p_skills.add_argument("-w", "--workspace", default=".")

    p_sess = sub.add_parser("sessions", help="List recorded JSONL sessions")
    p_sess.add_argument("-w", "--workspace", default=".")

    sub.add_parser("doctor", help="Inspect provider keys and sandbox dependencies")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()

    if args.subcommand == "run":
        return asyncio.run(_cmd_run(args, console))
    if args.subcommand == "chat":
        return asyncio.run(_cmd_chat(args, console))
    if args.subcommand == "pipeline":
        return asyncio.run(_cmd_pipeline(args, console))
    if args.subcommand == "skills":
        return _cmd_skills(args, console)
    if args.subcommand == "sessions":
        return _cmd_sessions(args, console)
    if args.subcommand == "doctor":
        return _cmd_doctor(console)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
