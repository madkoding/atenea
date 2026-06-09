"""Model-assisted route helpers must resolve endpoints with owner scope."""

from pathlib import Path

from tests.helpers.ast_check import assert_call_has_arg, assert_source_has

ROOT = Path(__file__).resolve().parents[1]


def test_document_ai_tidy_resolves_with_owner_scope():
    rp = ROOT / "routes/document_routes.py"
    assert_call_has_arg(rp, "resolve_task_endpoint", "owner")
    assert_call_has_arg(rp, "resolve_endpoint", "owner")


def test_calendar_quick_parse_resolves_with_owner_scope():
    rp = ROOT / "routes/calendar_routes.py"
    assert_source_has(rp, "owner = _require_user(request)")
    assert_call_has_arg(rp, "resolve_endpoint", "owner")


def test_task_parse_resolves_with_owner_scope():
    rp = ROOT / "routes/task_routes.py"
    assert_source_has(rp, "user = _owner(request)")
    assert_call_has_arg(rp, "resolve_endpoint", "owner")


def test_history_compact_resolves_with_owner_scope():
    rp = ROOT / "routes/history_routes.py"
    assert_source_has(rp, "owner = effective_user(request)")
    assert_call_has_arg(rp, "resolve_endpoint", "owner")


def test_note_reminder_synthesis_resolves_with_owner_scope():
    rp = ROOT / "routes/note_routes.py"
    assert_call_has_arg(rp, "resolve_endpoint", "owner")
