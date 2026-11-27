"""Hierarchical AGENTS.md discovery (OpenAI Codex & Google Gemini CLI pattern)."""

from __future__ import annotations

from pathlib import Path

CONTEXT_FILENAMES = ("AGENTS.md", "GEMINI.md", "CLAUDE.md")


def discover_agents_md(workspace: Path, max_chars_per_file: int = 16_000) -> str:
    """Walk from filesystem/git root down to workspace collecting project guide files."""
    resolved = workspace.resolve()
    chain: list[Path] = [resolved]
    cur = resolved
    while cur.parent != cur:
        if (cur / ".git").exists():
            break
        cur = cur.parent
        chain.append(cur)
    chain.reverse()

    sections: list[str] = []
    seen_paths: set[Path] = set()
    for directory in chain:
        for fname in CONTEXT_FILENAMES:
            candidate = directory / fname
            if candidate.is_file() and candidate not in seen_paths:
                seen_paths.add(candidate)
                raw = candidate.read_text(encoding="utf-8", errors="replace").strip()
                if raw:
                    clipped = raw[:max_chars_per_file]
                    sections.append(f"<!-- Guide: {candidate} -->\n{clipped}")
                break  # Prefer AGENTS.md over fallbacks in the same directory
    return "\n\n".join(sections)
