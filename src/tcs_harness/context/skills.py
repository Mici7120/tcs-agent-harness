"""Progressive-disclosure SKILL.md loader (Anthropic / Google ADK / Antigravity pattern)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str
    skill_file: Path
    body: str
    resources: list[str] = field(default_factory=list)


def _parse_skill_markdown(path: Path) -> SkillDefinition | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, object] = {}
    body = text

    if text.startswith("---\n"):
        end_idx = text.find("\n---", 4)
        if end_idx != -1:
            frontmatter = text[4:end_idx]
            body = text[end_idx + 4 :].lstrip("\n")
            parsed = yaml.safe_load(frontmatter)
            if isinstance(parsed, dict):
                meta = parsed

    name = str(meta.get("name") or path.parent.name).strip()
    description = str(meta.get("description") or "Specialized workflow skill.").strip()
    if not name:
        return None

    resources = sorted(
        str(p.relative_to(path.parent))
        for p in path.parent.rglob("*")
        if p.is_file() and p.name != "SKILL.md"
    )
    return SkillDefinition(
        name=name,
        description=description,
        skill_file=path,
        body=body.strip(),
        resources=resources,
    )


class SkillRegistry:
    """Discovers SKILL.md files and exposes a compact catalog + on-demand full loading."""

    def __init__(self, search_dirs: list[Path] | None = None) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        for directory in search_dirs or []:
            self.scan_directory(directory)

    def scan_directory(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for skill_md in sorted(directory.rglob("SKILL.md")):
            parsed = _parse_skill_markdown(skill_md)
            if parsed is not None:
                self._skills[parsed.name] = parsed

    def list_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def get_skill(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def render_catalog_prompt(self) -> str:
        if not self._skills:
            return ""
        lines = [
            "## Available Skills (Progressive Disclosure)",
            "Call `activate_skill` with `skill_name` BEFORE executing tasks matching a skill below:",
        ]
        for s in self._skills.values():
            lines.append(f"- **{s.name}**: {s.description}")
        return "\n".join(lines)

    def render_activated_skill(self, name: str) -> str:
        skill = self._skills.get(name)
        if skill is None:
            available = ", ".join(sorted(self._skills)) or "(none)"
            raise KeyError(f"Unknown skill '{name}'. Available skills: {available}")
        header = f"# Skill: {skill.name}\nDirectory: {skill.skill_file.parent}\n"
        res_block = ""
        if skill.resources:
            res_block = "\n\n## Bundled Resources\n" + "\n".join(f"- {r}" for r in skill.resources)
        return f"{header}\n{skill.body}{res_block}"
