"""Minimal-core surgical built-in tools (Pi + Codex + Gemini CLI synthesis)."""

from __future__ import annotations

import re
from typing import Any

from tcs_harness.context.skills import SkillRegistry
from tcs_harness.env.base import ExecutionEnvironment
from tcs_harness.tools.registry import ToolRegistry
from tcs_harness.types import ToolSpec

IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".tcs"}


def register_builtin_tools(
    registry: ToolRegistry,
    env: ExecutionEnvironment,
    skills: SkillRegistry | None = None,
) -> None:
    """Registers the minimal core coding & operations tools into a ToolRegistry."""

    def handle_read_file(args: dict[str, Any]) -> str:
        path = str(args["path"])
        text = env.read_text(path)
        lines = text.splitlines()
        start = max(1, int(args.get("start_line") or 1))
        end = min(len(lines), int(args.get("end_line") or min(len(lines), start + 399)))
        if not lines:
            return f"File '{path}' is empty."
        rendered = [f"{idx}: {lines[idx - 1]}" for idx in range(start, end + 1)]
        header = f"File: {path} (showing lines {start}-{end} of {len(lines)})"
        return header + "\n" + "\n".join(rendered)

    registry.register(
        ToolSpec(
            name="read_file",
            description="Read UTF-8 file contents from the workspace with 1-indexed line numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "start_line": {"type": "integer", "description": "Optional 1-indexed start line."},
                    "end_line": {"type": "integer", "description": "Optional 1-indexed inclusive end line."},
                },
                "required": ["path"],
            },
            read_only=True,
        ),
        handle_read_file,
    )

    def handle_write_file(args: dict[str, Any]) -> str:
        path = str(args["path"])
        content = str(args["content"])
        written = env.write_text(path, content)
        return f"Wrote {len(content)} chars to {written.relative_to(env.workspace)}."

    registry.register(
        ToolSpec(
            name="write_file",
            description="Create or overwrite a file inside the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "content": {"type": "string", "description": "Complete file content to write."},
                },
                "required": ["path", "content"],
            },
            read_only=False,
        ),
        handle_write_file,
    )

    def handle_edit_file(args: dict[str, Any]) -> str:
        path = str(args["path"])
        old_text = str(args["old_text"])
        new_text = str(args["new_text"])
        replace_all = bool(args.get("replace_all", False))

        if not old_text:
            raise ValueError("'old_text' must be non-empty.")
        current = env.read_text(path)
        occurrences = current.count(old_text)
        if occurrences == 0:
            raise ValueError(f"Exact 'old_text' not found in '{path}'. Read the file first to verify exact text.")
        if occurrences > 1 and not replace_all:
            raise ValueError(
                f"'old_text' matched {occurrences} locations in '{path}'. "
                "Provide more surrounding context or set replace_all=true."
            )
        updated = current.replace(old_text, new_text) if replace_all else current.replace(old_text, new_text, 1)
        env.write_text(path, updated)
        replaced = occurrences if replace_all else 1
        return f"Replaced {replaced} occurrence(s) in {path}."

    registry.register(
        ToolSpec(
            name="edit_file",
            description="Deterministically replace an exact text block in an existing file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative file path."},
                    "old_text": {"type": "string", "description": "Exact existing text to find."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences if true."},
                },
                "required": ["path", "old_text", "new_text"],
            },
            read_only=False,
        ),
        handle_edit_file,
    )

    def handle_search_files(args: dict[str, Any]) -> str:
        pattern = str(args["pattern"])
        subpath = str(args.get("path") or ".")
        root = env.resolve_path(subpath)
        regex = re.compile(pattern)
        matches: list[str] = []

        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for candidate in files:
            if not candidate.is_file():
                continue
            rel_parts = set(candidate.relative_to(env.workspace).parts)
            if rel_parts & IGNORED_DIRS:
                continue
            try:
                text = candidate.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            rel = candidate.relative_to(env.workspace)
            for line_no, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{rel}:{line_no}: {line.strip()[:200]}")
                    if len(matches) >= 100:
                        return "\n".join(matches) + "\n... (capped at 100 matches)"
        return "\n".join(matches) if matches else f"No matches found for pattern '{pattern}'."

    registry.register(
        ToolSpec(
            name="search_files",
            description="Search workspace text files using a regular expression.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression pattern to search for."},
                    "path": {"type": "string", "description": "Optional subdirectory or file path."},
                },
                "required": ["pattern"],
            },
            read_only=True,
        ),
        handle_search_files,
    )

    async def handle_run_bash(args: dict[str, Any]) -> str:
        command = str(args["command"])
        timeout_sec = float(args.get("timeout_sec") or 30.0)
        res = await env.run_command(command, timeout_sec=timeout_sec)
        return f"Exit code: {res.exit_code}\n{res.combined_output}"

    registry.register(
        ToolSpec(
            name="run_bash",
            description="Execute a stateless bash command in the execution environment (local or Docker sandbox).",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "timeout_sec": {"type": "number", "description": "Timeout in seconds (default 30)."},
                },
                "required": ["command"],
            },
            read_only=False,
        ),
        handle_run_bash,
    )

    if skills is not None and skills.list_skills():
        def handle_activate_skill(args: dict[str, Any]) -> str:
            return skills.render_activated_skill(str(args["skill_name"]))

        registry.register(
            ToolSpec(
                name="activate_skill",
                description="Load full SKILL.md instructions and resource paths for a named skill.",
                parameters={
                    "type": "object",
                    "properties": {
                        "skill_name": {"type": "string", "description": "Exact name of the skill to load."},
                    },
                    "required": ["skill_name"],
                },
                read_only=True,
            ),
            handle_activate_skill,
        )
