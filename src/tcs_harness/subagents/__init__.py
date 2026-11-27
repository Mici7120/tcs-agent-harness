"""Subagent delegation and multi-stage harness pipelines."""

from tcs_harness.subagents.orchestrator import (
    DEFAULT_SUBAGENT_PROFILES,
    PipelineOutcome,
    SubagentProfile,
    ThreeStagePipeline,
    register_subagent_tool,
)

__all__ = [
    "DEFAULT_SUBAGENT_PROFILES",
    "PipelineOutcome",
    "SubagentProfile",
    "ThreeStagePipeline",
    "register_subagent_tool",
]
