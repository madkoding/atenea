from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

# Import the route helper during collection so sibling session tests that use
# partial import stubs do not become the first loader of core.session_manager.
from routes.session_routes import _reject_raw_endpoint_url_for_non_admin
from tests.helpers.ast_check import assert_call_has_arg, assert_source_has


def _request(user, *, admin=False):
    auth_manager = SimpleNamespace(is_admin=lambda username: bool(admin))
    return SimpleNamespace(
        state=SimpleNamespace(current_user=user),
        app=SimpleNamespace(state=SimpleNamespace(auth_manager=auth_manager)),
    )


def test_non_admin_session_create_rejects_raw_endpoint_url_without_endpoint_id():
    with pytest.raises(HTTPException) as exc:
        _reject_raw_endpoint_url_for_non_admin(
            _request("alice", admin=False),
            "alice",
            "",
            "http://169.254.169.254/latest/meta-data",
        )

    assert exc.value.status_code == 403


def test_admin_and_registered_endpoint_can_use_endpoint_url():
    _reject_raw_endpoint_url_for_non_admin(
        _request("alice", admin=False),
        "alice",
        "endpoint-id",
        "http://127.0.0.1:8000/v1/chat/completions",
    )
    _reject_raw_endpoint_url_for_non_admin(
        _request("admin", admin=True),
        "admin",
        "",
        "http://127.0.0.1:8000/v1/chat/completions",
    )


def test_chat_endpoint_recovery_paths_are_owner_scoped():
    root = Path(__file__).resolve().parents[1]
    chat_routes = root / "routes" / "chat_routes.py"
    chat_helpers = root / "routes" / "chat_helpers.py"

    assert_source_has(chat_routes, "def _clear_orphaned_session_endpoint(sess, owner:")
    assert_source_has(chat_routes, "def _recover_empty_session_model(sess, session_id: str, owner:")
    assert_source_has(chat_routes, "q = owner_filter(q, ModelEndpoint, owner)")
    assert_call_has_arg(chat_routes, "resolve_session_auth", "owner")
    assert_source_has(chat_helpers, "def resolve_session_auth(sess, session_id: str, owner:")
    assert_source_has(chat_helpers, "update_q = update_q.filter(DBSession.owner == owner)")
