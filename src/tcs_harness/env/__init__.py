"""Execution environments (Local and Docker Sandbox)."""

from tcs_harness.env.base import CommandResult, ExecutionEnvironment
from tcs_harness.env.docker_sandbox import DockerSandboxEnvironment
from tcs_harness.env.local import LocalEnvironment, WorkspaceBoundaryError

__all__ = [
    "CommandResult",
    "DockerSandboxEnvironment",
    "ExecutionEnvironment",
    "LocalEnvironment",
    "WorkspaceBoundaryError",
]
