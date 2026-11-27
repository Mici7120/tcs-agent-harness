"""Token-threshold ContextCompactor inspired by Google ADK's EventsCompactionConfig."""

from __future__ import annotations

from dataclasses import dataclass

from tcs_harness.models.base import ModelProvider
from tcs_harness.types import CompactionConfig, Message, Role


@dataclass(slots=True)
class CompactionOutcome:
    compacted: bool
    before_tokens: int
    after_tokens: int
    summarized_count: int
    messages: list[Message]


SUMMARIZER_SYSTEM_PROMPT = (
    "You are a Context Compaction Engine inside an AI coding & operations harness. "
    "Summarize the conversation events concisely, preserving: (1) user goals & constraints, "
    "(2) files modified or inspected with exact paths, (3) key findings/errors, and "
    "(4) remaining next steps. Do NOT lose technical specifics."
)


class ContextCompactor:
    """Compresses older history turns when estimated token count crosses token_threshold."""

    def __init__(self, config: CompactionConfig) -> None:
        self.config = config

    @staticmethod
    def estimate_total_tokens(messages: list[Message]) -> int:
        return sum(m.estimate_tokens() for m in messages)

    def _find_safe_split_index(self, messages: list[Message]) -> int:
        """Keep the first user message (index 0) and at least tail_retention_messages at the end,
        without splitting an assistant tool_calls turn from its subsequent tool results."""
        keep_tail = max(2, self.config.tail_retention_messages)
        if len(messages) <= keep_tail + 2:
            return -1
        split_idx = len(messages) - keep_tail
        while split_idx > 1 and messages[split_idx].role == Role.TOOL:
            split_idx -= 1
        return split_idx if split_idx > 1 else -1

    @staticmethod
    def _deterministic_summary(chunk: list[Message]) -> str:
        bullets: list[str] = []
        for m in chunk:
            if m.role == Role.ASSISTANT and m.tool_calls:
                calls = ", ".join(tc.name for tc in m.tool_calls)
                bullets.append(f"- Assistant invoked tools: {calls}")
            elif m.role == Role.TOOL:
                snippet = m.content.replace("\n", " ")[:160]
                bullets.append(f"- Tool `{m.name}` output: {snippet}...")
            elif m.content:
                snippet = m.content.replace("\n", " ")[:200]
                bullets.append(f"- {m.role.value.capitalize()}: {snippet}")
        return "\n".join(bullets[:30])

    async def maybe_compact(
        self, messages: list[Message], provider: ModelProvider | None = None
    ) -> CompactionOutcome:
        before = self.estimate_total_tokens(messages)
        if not self.config.enabled or before < self.config.token_threshold:
            return CompactionOutcome(False, before, before, 0, messages)

        split_idx = self._find_safe_split_index(messages)
        if split_idx == -1:
            return CompactionOutcome(False, before, before, 0, messages)

        head = messages[:1]  # Preserve original user goal verbatim
        middle = messages[1:split_idx]
        tail = messages[split_idx:]

        summary_text = ""
        if self.config.use_llm_summarizer and provider is not None:
            transcript = "\n\n".join(
                f"[{m.role.value.upper()}{f' ({m.name})' if m.name else ''}]: {m.content[:1500]}"
                for m in middle
            )
            try:
                resp = await provider.generate(
                    messages=[
                        Message(
                            role=Role.USER,
                            content=f"Summarize these {len(middle)} historical turns:\n\n{transcript}",
                        )
                    ],
                    tools=None,
                    system_prompt=SUMMARIZER_SYSTEM_PROMPT,
                    temperature=0.0,
                )
                summary_text = resp.content.strip()
            except Exception:  # noqa: BLE001
                summary_text = ""

        if not summary_text:
            summary_text = self._deterministic_summary(middle)

        summary_msg = Message(
            role=Role.USER,
            content=(
                f"[Context Compaction Summary — {len(middle)} earlier messages compressed]\n"
                f"{summary_text}"
            ),
            metadata={"compacted_count": len(middle)},
        )
        new_messages = [*head, summary_msg, *tail]
        after = self.estimate_total_tokens(new_messages)
        return CompactionOutcome(
            compacted=True,
            before_tokens=before,
            after_tokens=after,
            summarized_count=len(middle),
            messages=new_messages,
        )
