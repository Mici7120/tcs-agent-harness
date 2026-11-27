"""Context management: AGENTS.md discovery, SKILL.md progressive disclosure, compaction, sessions."""

from tcs_harness.context.agents_md import discover_agents_md
from tcs_harness.context.compaction import CompactionOutcome, ContextCompactor
from tcs_harness.context.session import SessionStore
from tcs_harness.context.skills import SkillDefinition, SkillRegistry

__all__ = [
    "CompactionOutcome",
    "ContextCompactor",
    "SessionStore",
    "SkillDefinition",
    "SkillRegistry",
    "discover_agents_md",
]
