from pathlib import Path


CHAT_ROUTES = Path(__file__).resolve().parents[1] / "routes" / "chat_routes.py"


def _source() -> str:
    return CHAT_ROUTES.read_text(encoding="utf-8")


def test_chat_stream_uses_request_value_fallback_for_json_and_form():
    src = _source()
    assert "def _request_value(key: str, default: Any = None) -> Any:" in src
    assert "if key in form_data:" in src
    assert "if isinstance(body, dict):" in src


def test_chat_stream_tool_toggles_use_request_value_not_form_only():
    src = _source()
    assert 'allow_bash = _request_value("allow_bash")' in src
    assert 'allow_web_search = _request_value("allow_web_search")' in src
    assert 'if str(allow_bash).lower() != "true":' in src
    assert 'if str(allow_web_search).lower() != "true":' in src
    assert 'allow_bash = form_data.get("allow_bash")' not in src
    assert 'allow_web_search = form_data.get("allow_web_search")' not in src
