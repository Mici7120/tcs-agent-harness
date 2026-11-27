"""Append-only JSONL SessionStore for event trajectories and conversation resumption."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from tcs_harness.events import HarnessEvent
from tcs_harness.types import Message


class SessionStore:
    """Persists events and messages in .tcs/sessions/<session_id>/ as JSONL streams."""

    def __init__(self, base_dir: Path, session_id: str | None = None) -> None:
        self.base_dir = base_dir
        self.session_id = session_id or (
            datetime.now(UTC).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        )
        self.session_dir = self.base_dir / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.session_dir / "events.jsonl"
        self.messages_file = self.session_dir / "messages.jsonl"

    def append_event(self, event: HarnessEvent) -> None:
        with self.events_file.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")

    def save_messages(self, messages: list[Message]) -> None:
        with self.messages_file.open("w", encoding="utf-8") as fh:
            for msg in messages:
                fh.write(msg.model_dump_json() + "\n")

    def load_messages(self) -> list[Message]:
        if not self.messages_file.is_file():
            return []
        lines = self.messages_file.read_text(encoding="utf-8").splitlines()
        return [Message.model_validate_json(line) for line in lines if line.strip()]

    def load_events(self) -> list[HarnessEvent]:
        if not self.events_file.is_file():
            return []
        lines = self.events_file.read_text(encoding="utf-8").splitlines()
        return [HarnessEvent.model_validate_json(line) for line in lines if line.strip()]

    @classmethod
    def list_sessions(cls, base_dir: Path) -> list[str]:
        if not base_dir.is_dir():
            return []
        return sorted(
            (p.name for p in base_dir.iterdir() if p.is_dir()),
            reverse=True,
        )
