"""Declarative PolicyEngine inspired by Gemini CLI's PolicyEngine & Codex approval tiers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from tcs_harness.types import ToolCall, ToolSpec


class PolicyAction(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ApprovalMode(StrEnum):
    """Four standard approval postures modeled after Gemini CLI and Codex."""

    READ_ONLY = "read_only"      # Only read_only tools allowed; mutating/bash denied
    STRICT_ASK = "strict_ask"    # Read-only allowed; all edits and shell ask confirmation
    AUTO_EDIT = "auto_edit"      # File edits allowed in workspace; shell commands ask (default)
    AUTONOMOUS = "autonomous"    # Edits & safe shell allowed; dangerous patterns still denied/asked


@dataclass(slots=True)
class PolicyRule:
    tool_name: str
    action: PolicyAction
    command_regex: str | None = None
    reason: str = ""

    def matches(self, call: ToolCall) -> bool:
        if self.tool_name not in ("*", call.name):
            return False
        if self.command_regex is not None:
            cmd = str(call.arguments.get("command", ""))
            return re.search(self.command_regex, cmd) is not None
        return True


@dataclass(slots=True)
class PolicyEvaluation:
    action: PolicyAction
    reason: str


DEFAULT_DENY_PATTERNS: list[tuple[str, str]] = [
    (r"(^|\s)rm\s+-rf\s+/(\s|$)", "Destructive root filesystem deletion is forbidden."),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "Fork bombs are forbidden."),
    (r"git\s+push\s+.*--force.*\s+(main|master)\b", "Force-pushing to main/master is forbidden."),
    (r"mkfs\.", "Formatting block devices is forbidden."),
]

DEFAULT_ASK_PATTERNS: list[tuple[str, str]] = [
    (r"\bsudo\b", "Privilege escalation via sudo requires explicit approval."),
    (r"curl\s+.*\|\s*(ba)?sh", "Piping remote scripts directly to shell requires approval."),
    (r"\bgit\s+push\b", "Pushing commits to remote requires approval."),
]


class PolicyEngine:
    """Evaluates every ToolCall before execution."""

    def __init__(
        self,
        mode: ApprovalMode = ApprovalMode.AUTO_EDIT,
        custom_rules: list[PolicyRule] | None = None,
    ) -> None:
        self.mode = mode
        self.custom_rules: list[PolicyRule] = list(custom_rules or [])

    def evaluate(self, call: ToolCall, spec: ToolSpec | None = None) -> PolicyEvaluation:
        # 1. Hard safety guardrails on shell commands always run first
        if call.name == "run_bash":
            cmd = str(call.arguments.get("command", ""))
            for pattern, reason in DEFAULT_DENY_PATTERNS:
                if re.search(pattern, cmd):
                    return PolicyEvaluation(PolicyAction.DENY, reason)

        # 2. User-provided custom rules take precedence over mode defaults
        for rule in self.custom_rules:
            if rule.matches(call):
                return PolicyEvaluation(rule.action, rule.reason or "Matched custom policy rule.")

        # 3. Read-only mode blocks any non-read-only tool
        is_read_only = bool(spec and spec.read_only)
        if self.mode == ApprovalMode.READ_ONLY:
            if is_read_only:
                return PolicyEvaluation(PolicyAction.ALLOW, "Read-only tool allowed.")
            return PolicyEvaluation(
                PolicyAction.DENY,
                f"Tool '{call.name}' is blocked because agent is running in READ_ONLY mode.",
            )

        # 4. Ask patterns for risky bash operations even in AUTONOMOUS mode
        if call.name == "run_bash":
            cmd = str(call.arguments.get("command", ""))
            for pattern, reason in DEFAULT_ASK_PATTERNS:
                if re.search(pattern, cmd):
                    return PolicyEvaluation(PolicyAction.ASK, reason)

        if is_read_only:
            return PolicyEvaluation(PolicyAction.ALLOW, "Read-only tool allowed.")

        if self.mode == ApprovalMode.STRICT_ASK:
            return PolicyEvaluation(
                PolicyAction.ASK, f"STRICT_ASK mode requires confirmation for '{call.name}'."
            )

        if self.mode == ApprovalMode.AUTO_EDIT:
            if call.name in ("write_file", "edit_file", "activate_skill", "delegate_subagent"):
                return PolicyEvaluation(
                    PolicyAction.ALLOW, f"Workspace tool '{call.name}' allowed in AUTO_EDIT mode."
                )
            return PolicyEvaluation(
                PolicyAction.ASK, f"Tool '{call.name}' requires confirmation in AUTO_EDIT mode."
            )

        return PolicyEvaluation(PolicyAction.ALLOW, "Allowed in AUTONOMOUS mode.")
