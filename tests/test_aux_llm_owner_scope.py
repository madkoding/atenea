from pathlib import Path

from tests.helpers.ast_check import assert_call_has_arg, assert_source_does_not_have, assert_source_has

ROOT = Path(__file__).resolve().parents[1]


def test_registered_manual_compaction_uses_session_owner_for_utility_endpoint():
    assert_source_has(ROOT / "routes/session_routes.py", 'owner = getattr(session, "owner", None) or effective_user(request)')
    assert_call_has_arg(ROOT / "routes/session_routes.py", "resolve_endpoint", "owner")


def test_task_name_generation_uses_owner_scoped_session_endpoint():
    rp = ROOT / "routes/task_routes.py"
    assert_source_has(rp, "async def _generate_task_name(prompt: str, owner: str | None = None)")
    assert_source_has(rp, "q = q.filter(DbSession.owner == owner)")
    assert_source_has(rp, "headers = recent.headers or {}")
    assert_source_has(rp, "headers=headers")
    assert_call_has_arg(rp, "_generate_task_name", "owner")


def test_auto_compaction_utility_endpoint_keeps_chat_owner():
    helper_rp = ROOT / "routes/chat_helpers.py"
    compact_rp = ROOT / "src/chat/context_compactor.py"
    assert_source_has(helper_rp, "owner=user")
    assert_source_has(compact_rp, "owner: str | None = None")
    assert_call_has_arg(compact_rp, "resolve_endpoint", "owner")


def test_background_session_sort_uses_owner_task_endpoint():
    assert_call_has_arg(ROOT / "src/misc/session_actions.py", "resolve_task_endpoint", "owner")


def test_scheduler_fallbacks_and_research_headers_are_owner_scoped():
    rp = ROOT / "src/scheduling/task_scheduler.py"
    assert_call_has_arg(rp, "resolve_utility_fallback_candidates", "owner")
    assert_call_has_arg(rp, "resolve_endpoint", "owner")
    assert_source_has(rp, "owner=task.owner or None")
    assert_source_has(rp, "headers_from_resolver = False")
    assert_source_has(rp, "headers_from_resolver = True")
    assert_source_has(rp, "from src.auth.helpers import owner_filter")
    assert_source_has(rp, "owner_filter(ep_q, ModelEndpoint, task.owner or None)")


def test_research_routes_fallbacks_are_owner_scoped():
    rp = ROOT / "routes/research_routes.py"
    assert_call_has_arg(rp, "resolve_endpoint", "owner")
    assert_source_has(rp, "ep = _owned_enabled_endpoint(db, user)")
    # Verify no unowned endpoint fallback (no direct query without owner filter)
    assert_source_does_not_have(rp, "db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).first()")
    assert_source_has(rp, 'getattr(sess, "owner", None) or None')
