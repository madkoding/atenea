from pathlib import Path

from tests.helpers.ast_check import assert_contains_call, assert_source_does_not_have, assert_source_has

CHAT_ROUTES = Path(__file__).resolve().parents[1] / "routes" / "chat_routes.py"


def test_chat_stream_uses_request_value_fallback_for_json_and_form():
    assert_source_has(CHAT_ROUTES, "def _request_value(key: str, default: Any = None) -> Any:")
    assert_source_has(CHAT_ROUTES, "if key in form_data:")
    assert_source_has(CHAT_ROUTES, "if isinstance(body, dict):")


def test_chat_stream_tool_toggles_use_request_value_not_form_only():
    assert_contains_call(CHAT_ROUTES, "_request_value")
    assert_source_has(CHAT_ROUTES, 'if str(allow_bash).lower() != "true":')
    assert_source_has(CHAT_ROUTES, 'if str(allow_web_search).lower() != "true":')
    # Negative assertions: verify no direct form_data access for tool toggles
    assert_source_does_not_have(CHAT_ROUTES, 'allow_bash = form_data.get("allow_bash")')
    assert_source_does_not_have(CHAT_ROUTES, 'allow_web_search = form_data.get("allow_web_search")')
