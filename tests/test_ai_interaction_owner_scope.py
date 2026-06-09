from pathlib import Path

import pytest

import src.agent.ai_interaction as ai_interaction
from tests.helpers.ast_check import assert_call_has_arg, assert_source_has

AI_PATH = Path(ai_interaction.__file__)


def test_model_resolver_applies_owner_filter():
    assert_source_has(AI_PATH, "owner: Optional[str] = None")
    assert_source_has(AI_PATH, "from src.auth.helpers import owner_filter")
    assert_source_has(AI_PATH, "owner_filter(query, ModelEndpoint, owner)")


def test_model_listing_and_image_fallback_are_owner_scoped():
    assert_source_has(AI_PATH, "owner: Optional[str] = None")
    assert_source_has(AI_PATH, "owner_filter(query, ModelEndpoint, owner)")
    assert_call_has_arg(AI_PATH, "_resolve_model", "owner")
    assert_source_has(AI_PATH, "owner_filter(_img_q, ModelEndpoint, owner)")


@pytest.mark.parametrize("tool,content", [
    ("chat_with_model", "gpt-test\nhello"),
    ("pipeline", "gpt-test | summarize this"),
    ("list_models", ""),
    ("ui_control", "switch_model gpt-test"),
    ("ask_teacher", "gpt-test\nhelp me"),
])
async def test_dispatch_passes_owner_to_model_tools(monkeypatch, tool, content):
    seen = {}

    async def capture(name, content, session_id=None, owner=None):
        seen[name] = {"content": content, "session_id": session_id, "owner": owner}
        return {"ok": True}

    monkeypatch.setattr(
        ai_interaction,
        "do_chat_with_model",
        lambda content, session_id=None, owner=None: capture("chat_with_model", content, session_id, owner),
    )
    monkeypatch.setattr(
        ai_interaction,
        "do_pipeline",
        lambda content, session_id=None, owner=None: capture("pipeline", content, session_id, owner),
    )
    monkeypatch.setattr(
        ai_interaction,
        "do_list_models",
        lambda content, session_id=None, owner=None: capture("list_models", content, session_id, owner),
    )
    monkeypatch.setattr(
        ai_interaction,
        "do_ui_control",
        lambda content, session_id=None, owner=None: capture("ui_control", content, session_id, owner),
    )
    monkeypatch.setattr(
        ai_interaction,
        "do_ask_teacher",
        lambda content, session_id=None, owner=None: capture("ask_teacher", content, session_id, owner),
    )

    _desc, result = await ai_interaction.dispatch_ai_tool(tool, content, session_id="sid1", owner="alice")

    assert result == {"ok": True}
    assert seen[tool]["owner"] == "alice"
    assert seen[tool]["session_id"] == "sid1"
