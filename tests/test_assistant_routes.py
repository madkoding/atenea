from datetime import UTC, datetime
from types import SimpleNamespace

import routes.assistant_routes as assistant_routes


def test_decode_tools_handles_invalid_or_non_list_payloads():
    assert assistant_routes._decode_tools("not-json") == []
    assert assistant_routes._decode_tools('{"a": 1}') == []
    assert assistant_routes._decode_tools(None) == []


def test_decode_tools_parses_valid_list_json():
    assert assistant_routes._decode_tools('["send_email", "calendar_create"]') == [
        "send_email",
        "calendar_create",
    ]


def test_with_autonomous_email_toggle_adds_and_removes_email_tools():
    base = ["calendar_create"]
    enabled = assistant_routes._with_autonomous_email_toggle(list(base), True)
    assert "send_email" in enabled
    assert "reply_to_email" in enabled
    assert "calendar_create" in enabled

    disabled = assistant_routes._with_autonomous_email_toggle(enabled, False)
    assert "send_email" not in disabled
    assert "reply_to_email" not in disabled
    assert "calendar_create" in disabled


def test_apply_checkin_update_recomputes_next_run_on_time_change(monkeypatch):
    captured = {}

    def _fake_compute_next_run(*args, **kwargs):
        captured["called"] = True
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "NEXT-RUN"

    monkeypatch.setattr(assistant_routes, "compute_next_run", _fake_compute_next_run)

    task = SimpleNamespace(
        name="Morning",
        scheduled_time="08:00",
        prompt="hello",
        status="paused",
        schedule="daily",
        scheduled_day=None,
        scheduled_date=None,
        cron_expression=None,
        next_run=None,
        updated_at=None,
    )
    check_in = assistant_routes.CheckInUpdate(
        id="task-1",
        name="  New Morning  ",
        scheduled_time="09:30",
        prompt="new prompt",
        enabled=True,
    )
    now_utc = datetime.now(UTC).replace(tzinfo=None)

    assistant_routes._apply_checkin_update(task, check_in, now_utc, "UTC")

    assert task.name == "New Morning"
    assert task.scheduled_time == "09:30"
    assert task.prompt == "new prompt"
    assert task.status == "active"
    assert task.next_run == "NEXT-RUN"
    assert captured.get("called") is True
    assert captured["kwargs"]["tz_name"] == "UTC"


def test_recompute_task_next_run_requires_schedule_and_time(monkeypatch):
    calls = {"count": 0}

    def _fake_compute_next_run(*args, **kwargs):
        calls["count"] += 1
        return "NEXT"

    monkeypatch.setattr(assistant_routes, "compute_next_run", _fake_compute_next_run)

    now_utc = datetime.now(UTC).replace(tzinfo=None)
    missing_schedule = SimpleNamespace(
        schedule=None,
        scheduled_time="08:00",
        scheduled_day=None,
        scheduled_date=None,
        cron_expression=None,
        next_run=None,
    )
    missing_time = SimpleNamespace(
        schedule="daily",
        scheduled_time=None,
        scheduled_day=None,
        scheduled_date=None,
        cron_expression=None,
        next_run=None,
    )
    valid = SimpleNamespace(
        schedule="daily",
        scheduled_time="08:00",
        scheduled_day=None,
        scheduled_date=None,
        cron_expression=None,
        next_run=None,
    )

    assistant_routes._recompute_task_next_run(missing_schedule, now_utc, "UTC")
    assistant_routes._recompute_task_next_run(missing_time, now_utc, "UTC")
    assistant_routes._recompute_task_next_run(valid, now_utc, "UTC")

    assert calls["count"] == 1
    assert valid.next_run == "NEXT"


def test_crew_to_dict_uses_decoded_tools_for_autonomous_email_flag():
    crew = SimpleNamespace(
        id="crew-1",
        name="Assistant",
        avatar="avatar.png",
        personality="calm",
        model="model",
        endpoint_url="http://example",
        greeting="hi",
        enabled_tools='["calendar_create", "send_email"]',
        session_id="session-1",
        is_default_assistant=True,
        timezone="UTC",
    )

    out = assistant_routes._crew_to_dict(crew)

    assert out["enabled_tools"] == ["calendar_create", "send_email"]
    assert out["allow_autonomous_email"] is True
