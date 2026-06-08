"""Agent orchestration.

This package groups the agent-side helpers that the chat and tools
layers call into:

- ``runs`` — persistent run history.
- ``tools_facade`` — backward-compatible re-exports of the old
  ``src.agent_tools`` module.
- ``ai_interaction`` — chat-with-model, debate, pipeline, self-managing AI.
- ``assistant_log`` — per-user assistant log helpers.
- ``teacher_escalation`` — the “ask the teacher” flow.

The facade is kept for callers that still import ``src.agent_tools``;
new code should import the specific submodule.
"""
from src.agent.tools_facade import *  # noqa: F401,F403
from src.agent.tools_facade import (  # noqa: F401
    ToolBlock,
    TOOL_TAGS,
    MAX_AGENT_ROUNDS,
    SHELL_TIMEOUT,
    PYTHON_TIMEOUT,
    set_mcp_manager,
    get_mcp_manager,
    _truncate,
)
