"""Docker Sandbox environment inspired by OpenHands and mini-swe-agent."""

from __future__ import annotations

import asyncio
import shlex
import uuid
from pathlib import Path
from typing import Self

from tcs_harness.env.base import CommandResult
from tcs_harness.env.local import LocalEnvironment


class DockerSandboxEnvironment(LocalEnvironment):
    """Runs commands inside an isolated Docker container with bind-mounted /workspace."""

    def __init__(
        self,
        workspace: Path,
        image: str = "python:3.12-slim",
        network_disabled: bool = True,
        memory_limit: str = "1g",
        cpus: str = "2.0",
    ) -> None:
        super().__init__(workspace=workspace)
        self.image = image
        self.network_disabled = network_disabled
        self.memory_limit = memory_limit
        self.cpus = cpus
        self.container_name = f"tcs-sandbox-{uuid.uuid4().hex[:8]}"
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        net_args = ["--network", "none"] if self.network_disabled else []
        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self.container_name,
            "--memory",
            self.memory_limit,
            "--cpus",
            self.cpus,
            *net_args,
            "-v",
            f"{self.workspace}:/workspace",
            "-w",
            "/workspace",
            self.image,
            "sleep",
            "infinity",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Failed to start Docker sandbox '{self.image}': {err.decode('utf-8', errors='replace').strip()}"
            )
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            self.container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        self._started = False

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.stop()

    async def run_command(self, command: str, timeout_sec: float = 30.0) -> CommandResult:
        if not self._started:
            await self.start()
        exec_cmd = f"docker exec -w /workspace {shlex.quote(self.container_name)} sh -lc {shlex.quote(command)}"
        return await super().run_command(exec_cmd, timeout_sec=timeout_sec)
