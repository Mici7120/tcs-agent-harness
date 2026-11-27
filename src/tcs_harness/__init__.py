"""tcs-agent-harness: Modular open-source AI Agent Harness."""

from tcs_harness.context import ContextCompactor, SessionStore, SkillRegistry, discover_agents_md
from tcs_harness.env import DockerSandboxEnvironment, ExecutionEnvironment, LocalEnvironment
from tcs_harness.events import EventType, HarnessEvent
from tcs_harness.mcp import StdioMcpClient
from tcs_harness.models import (
    AnthropicProvider,
    GeminiProvider,
    ModelProvider,
    OpenAICompatibleProvider,
    RecordingModelProvider,
    ScriptedModelProvider,
    create_model_provider,
)
from tcs_harness.policy import (
    ApprovalMode,
    AutoApproveBus,
    CallbackConfirmationBus,
    CommandStopGate,
    DenyAllBus,
    HookManager,
    PolicyAction,
    PolicyEngine,
    PolicyRule,
)
from tcs_harness.runner import AgentRunner, RunResult
from tcs_harness.subagents import SubagentProfile, ThreeStagePipeline, register_subagent_tool
from tcs_harness.tools import ToolRegistry, register_builtin_tools
from tcs_harness.types import (
    CompactionConfig,
    HarnessConfig,
    Message,
    ModelResponse,
    Role,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolSpec,
)

__version__ = "0.1.0"

__all__ = [
    "AgentRunner",
    "AnthropicProvider",
    "ApprovalMode",
    "AutoApproveBus",
    "CallbackConfirmationBus",
    "CommandStopGate",
    "CompactionConfig",
    "ContextCompactor",
    "DenyAllBus",
    "DockerSandboxEnvironment",
    "EventType",
    "ExecutionEnvironment",
    "GeminiProvider",
    "HarnessConfig",
    "HarnessEvent",
    "HookManager",
    "LocalEnvironment",
    "Message",
    "ModelProvider",
    "ModelResponse",
    "OpenAICompatibleProvider",
    "PolicyAction",
    "PolicyEngine",
    "PolicyRule",
    "RecordingModelProvider",
    "Role",
    "RunResult",
    "ScriptedModelProvider",
    "SessionStore",
    "SkillRegistry",
    "StdioMcpClient",
    "SubagentProfile",
    "ThreeStagePipeline",
    "TokenUsage",
    "ToolCall",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "create_model_provider",
    "discover_agents_md",
    "register_builtin_tools",
    "register_subagent_tool",
]
