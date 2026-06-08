"""Tool-block primitives shared across the tool runtime.

``ToolBlock`` and ``TOOL_TAGS`` are used by both the agent facade
(``src.agent_tools``) and the individual tool submodules
(``src.tools.schemas``, ``src.tools.execution``, ...). Defining them here
breaks the historical circular import: nothing in this module imports
back into the tool runtime, so it can be imported safely from anywhere.
"""
from collections import namedtuple

# ToolBlock is the in-memory representation of a tool call. The tool
# runtime's parser produces these; the executor consumes them.
ToolBlock = namedtuple("ToolBlock", ["tool_type", "content"])

# Tags the executor actually understands. ``agent_tools`` may extend this
# with additional tags that the chat layer (not the agent) handles, so
# both layers keep their own copy via ``TOOL_TAGS``/``CHAT_TOOL_TAGS``.
TOOL_TAGS = {
    "bash", "python", "web_search", "web_fetch", "read_file", "write_file",
    "edit_file", "grep", "glob", "ls",
    "create_document", "update_document", "edit_document",
    "search_chats",
    "chat_with_model", "create_session", "list_sessions",
    "send_to_session",
    "pipeline",
    "manage_session", "manage_memory", "list_models",
    "ui_control", "generate_image", "ask_user", "update_plan",
    "manage_tasks", "api_call", "ask_teacher", "manage_skills",
    "suggest_document",
    "manage_endpoints", "manage_mcp", "manage_webhooks",
    "manage_tokens", "manage_documents", "manage_settings",
    "manage_notes", "manage_calendar",
    "resolve_contact", "manage_contact",
    "list_email_accounts", "send_email", "list_emails",
    "read_email", "reply_to_email", "bulk_email", "archive_email",
    "delete_email", "mark_email_read",
    "download_model", "serve_model",
    "list_served_models", "stop_served_model",
    "list_downloads", "cancel_download",
    "search_hf_models", "list_cached_models",
    "list_serve_presets", "serve_preset", "adopt_served_model",
    "list_cookbook_servers",
    "edit_image", "trigger_research", "manage_research",
    "app_api",
}


__all__ = ["ToolBlock", "TOOL_TAGS"]
