import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routes.assistant_routes as assistant_routes


class _FakeColumn:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return ("eq", self.name, value)

    def asc(self):
        return ("asc", self.name)

    def desc(self):
        return ("desc", self.name)


class _CrewMemberModel:
    owner = _FakeColumn("owner")
    is_default_assistant = _FakeColumn("is_default_assistant")
    id = _FakeColumn("id")


class _ScheduledTaskModel:
    id = _FakeColumn("id")
    owner = _FakeColumn("owner")
    crew_member_id = _FakeColumn("crew_member_id")
    scheduled_time = _FakeColumn("scheduled_time")


class _TaskRunModel:
    task_id = _FakeColumn("task_id")
    started_at = _FakeColumn("started_at")


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *conditions):
        for condition in conditions:
            if isinstance(condition, tuple) and condition[0] == "eq":
                _, field, value = condition
                self._rows = [row for row in self._rows if getattr(row, field) == value]
        return self

    def order_by(self, *orderings):
        for ordering in orderings:
            if isinstance(ordering, tuple) and ordering[0] in {"asc", "desc"}:
                direction, field = ordering
                self._rows = sorted(
                    self._rows,
                    key=lambda row: getattr(row, field),
                    reverse=direction == "desc",
                )
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, model_rows):
        self._model_rows = model_rows
        self.commits = 0

    def query(self, model):
        return _FakeQuery(self._model_rows.get(model, []))

    def close(self):
        return None

    def commit(self):
        self.commits += 1


class _Scheduler:
    def __init__(self):
        self.owners = []

    async def ensure_assistant_defaults(self, owner):
        self.owners.append(owner)

    async def run_task_now(self, _task_id):
        return True


class _RunScheduler(_Scheduler):
    def __init__(self, started):
        super().__init__()
        self.started = started
        self.called_with = []

    async def run_task_now(self, task_id):
        self.called_with.append(task_id)
        return self.started


def _endpoint(router, method, path):
    method = method.upper()
    for route in router.routes:
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            return route.endpoint
    raise KeyError(f"Route {method} {path} not found")


def _install_models(monkeypatch):
    monkeypatch.setattr(assistant_routes, "CrewMember", _CrewMemberModel)
    monkeypatch.setattr(assistant_routes, "ScheduledTask", _ScheduledTaskModel)


def test_assistant_session_requires_authenticated_user(monkeypatch):
    _install_models(monkeypatch)
    monkeypatch.setattr(assistant_routes, "get_current_user", lambda _request: None)
    router = assistant_routes.setup_assistant_routes(_Scheduler())
    get_session = _endpoint(router, "GET", "/api/assistant/session")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_session(SimpleNamespace()))

    assert exc.value.status_code == 401


def test_assistant_session_rejects_synthetic_owner(monkeypatch):
    _install_models(monkeypatch)
    monkeypatch.setattr(assistant_routes, "get_current_user", lambda _request: "api")
    monkeypatch.setattr(assistant_routes, "SessionLocal", lambda: _FakeDb({}))
    router = assistant_routes.setup_assistant_routes(_Scheduler())
    get_session = _endpoint(router, "GET", "/api/assistant/session")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_session(SimpleNamespace()))

    assert exc.value.status_code == 400
    assert "Cannot seed assistant" in exc.value.detail


def test_assistant_settings_returns_checkins_and_task_ids(monkeypatch):
    _install_models(monkeypatch)
    monkeypatch.setattr(assistant_routes, "get_current_user", lambda _request: "alice")

    crew = SimpleNamespace(
        id="crew-1",
        owner="alice",
        is_default_assistant=True,
        session_id="session-1",
        name="Assistant",
        avatar=None,
        personality="helpful",
        model="m1",
        endpoint_url=None,
        greeting="hi",
        enabled_tools='["send_email"]',
        timezone="UTC",
    )
    tasks = [
        SimpleNamespace(
            id="task-1",
            owner="alice",
            crew_member_id="crew-1",
            name="Morning",
            scheduled_time="08:00",
            prompt="hello",
            status="active",
            next_run=None,
            last_run=None,
            run_count=0,
        ),
        SimpleNamespace(
            id="task-2",
            owner="alice",
            crew_member_id="crew-1",
            name="Evening",
            scheduled_time="18:00",
            prompt="bye",
            status="paused",
            next_run=None,
            last_run=None,
            run_count=2,
        ),
    ]
    db = _FakeDb({_CrewMemberModel: [crew], _ScheduledTaskModel: tasks})
    monkeypatch.setattr(assistant_routes, "SessionLocal", lambda: db)

    router = assistant_routes.setup_assistant_routes(_Scheduler())
    get_settings = _endpoint(router, "GET", "/api/assistant/settings")
    out = asyncio.run(get_settings(SimpleNamespace()))

    assert out["crew"]["id"] == "crew-1"
    assert out["crew"]["allow_autonomous_email"] is True
    assert out["task_ids"] == ["task-1", "task-2"]
    assert [ci["id"] for ci in out["check_ins"]] == ["task-1", "task-2"]


def test_run_status_is_owner_scoped(monkeypatch):
    import core.database as core_db

    _install_models(monkeypatch)
    monkeypatch.setattr(core_db, "ScheduledTask", _ScheduledTaskModel, raising=False)
    monkeypatch.setattr(core_db, "TaskRun", _TaskRunModel, raising=False)
    monkeypatch.setattr(assistant_routes, "get_current_user", lambda _request: "alice")

    foreign_task = SimpleNamespace(id="task-x", owner="bob")
    db = _FakeDb({_ScheduledTaskModel: [foreign_task], _TaskRunModel: []})
    monkeypatch.setattr(assistant_routes, "SessionLocal", lambda: db)

    router = assistant_routes.setup_assistant_routes(_Scheduler())
    run_status = _endpoint(router, "GET", "/api/assistant/run-status/{task_id}")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run_status("task-x", SimpleNamespace()))

    assert exc.value.status_code == 404


def test_run_status_returns_done_for_finished_last_run(monkeypatch):
    import core.database as core_db

    _install_models(monkeypatch)
    monkeypatch.setattr(core_db, "ScheduledTask", _ScheduledTaskModel, raising=False)
    monkeypatch.setattr(core_db, "TaskRun", _TaskRunModel, raising=False)
    monkeypatch.setattr(assistant_routes, "get_current_user", lambda _request: "alice")

    owned_task = SimpleNamespace(id="task-1", owner="alice")
    now = datetime.now(UTC).replace(tzinfo=None)
    runs = [
        SimpleNamespace(task_id="task-1", started_at=now - timedelta(minutes=10), status="running"),
        SimpleNamespace(task_id="task-1", started_at=now, status="failed"),
    ]
    db = _FakeDb({_ScheduledTaskModel: [owned_task], _TaskRunModel: runs})
    monkeypatch.setattr(assistant_routes, "SessionLocal", lambda: db)

    router = assistant_routes.setup_assistant_routes(_Scheduler())
    run_status = _endpoint(router, "GET", "/api/assistant/run-status/{task_id}")
    out = asyncio.run(run_status("task-1", SimpleNamespace()))

    assert out == {"status": "done", "result_status": "failed"}


def test_patch_settings_toggle_autonomous_email_updates_tools(monkeypatch):
    _install_models(monkeypatch)
    monkeypatch.setattr(assistant_routes, "get_current_user", lambda _request: "alice")

    crew = SimpleNamespace(
        id="crew-1",
        owner="alice",
        is_default_assistant=True,
        session_id="session-1",
        name="Assistant",
        avatar=None,
        personality="helpful",
        model="m1",
        endpoint_url=None,
        greeting="hi",
        enabled_tools='["send_email", "reply_to_email", "calendar_create"]',
        timezone="UTC",
        updated_at=None,
    )
    task = SimpleNamespace(
        id="task-1",
        owner="alice",
        crew_member_id="crew-1",
        name="Morning",
        scheduled_time="08:00",
        prompt="hello",
        status="active",
        next_run=None,
        last_run=None,
        run_count=0,
        schedule="daily",
        scheduled_day=None,
        scheduled_date=None,
        cron_expression=None,
        updated_at=None,
    )
    db = _FakeDb({_CrewMemberModel: [crew], _ScheduledTaskModel: [task]})
    monkeypatch.setattr(assistant_routes, "SessionLocal", lambda: db)

    router = assistant_routes.setup_assistant_routes(_Scheduler())
    patch_settings = _endpoint(router, "PATCH", "/api/assistant/settings")

    payload = assistant_routes.AssistantSettingsUpdate(allow_autonomous_email=False)
    out = asyncio.run(patch_settings(payload, SimpleNamespace()))

    assert db.commits == 1
    assert out["crew"]["enabled_tools"] == ["calendar_create"]
    assert out["crew"]["allow_autonomous_email"] is False


def test_patch_settings_timezone_recomputes_next_run_for_all_checkins(monkeypatch):
    _install_models(monkeypatch)
    monkeypatch.setattr(assistant_routes, "get_current_user", lambda _request: "alice")

    calls = []

    def _fake_compute_next_run(*args, **kwargs):
        calls.append((args, kwargs))
        return datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=len(calls))

    monkeypatch.setattr(assistant_routes, "compute_next_run", _fake_compute_next_run)

    crew = SimpleNamespace(
        id="crew-1",
        owner="alice",
        is_default_assistant=True,
        session_id="session-1",
        name="Assistant",
        avatar=None,
        personality="helpful",
        model="m1",
        endpoint_url=None,
        greeting="hi",
        enabled_tools="[]",
        timezone="UTC",
        updated_at=None,
    )
    task_a = SimpleNamespace(
        id="task-1",
        owner="alice",
        crew_member_id="crew-1",
        name="Morning",
        scheduled_time="08:00",
        prompt="hello",
        status="active",
        next_run=None,
        last_run=None,
        run_count=0,
        schedule="daily",
        scheduled_day=None,
        scheduled_date=None,
        cron_expression=None,
        updated_at=None,
    )
    task_b = SimpleNamespace(
        id="task-2",
        owner="alice",
        crew_member_id="crew-1",
        name="Evening",
        scheduled_time="18:00",
        prompt="bye",
        status="paused",
        next_run=None,
        last_run=None,
        run_count=0,
        schedule="daily",
        scheduled_day=None,
        scheduled_date=None,
        cron_expression=None,
        updated_at=None,
    )
    db = _FakeDb({_CrewMemberModel: [crew], _ScheduledTaskModel: [task_a, task_b]})
    monkeypatch.setattr(assistant_routes, "SessionLocal", lambda: db)

    router = assistant_routes.setup_assistant_routes(_Scheduler())
    patch_settings = _endpoint(router, "PATCH", "/api/assistant/settings")

    payload = assistant_routes.AssistantSettingsUpdate(timezone="America/Bogota")
    out = asyncio.run(patch_settings(payload, SimpleNamespace()))

    assert db.commits == 1
    assert len(calls) == 2
    assert all(call[1]["tz_name"] == "America/Bogota" for call in calls)
    assert {ci["id"] for ci in out["check_ins"]} == {"task-1", "task-2"}


def test_run_now_returns_404_when_task_not_found(monkeypatch):
    _install_models(monkeypatch)
    monkeypatch.setattr(assistant_routes, "get_current_user", lambda _request: "alice")

    db = _FakeDb({_ScheduledTaskModel: [], _CrewMemberModel: []})
    monkeypatch.setattr(assistant_routes, "SessionLocal", lambda: db)

    scheduler = _RunScheduler(started=True)
    router = assistant_routes.setup_assistant_routes(scheduler)
    run_now = _endpoint(router, "POST", "/api/assistant/run/{task_id}")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run_now("task-x", SimpleNamespace()))

    assert exc.value.status_code == 404
    assert scheduler.called_with == []


def test_run_now_returns_400_for_non_assistant_task(monkeypatch):
    _install_models(monkeypatch)
    monkeypatch.setattr(assistant_routes, "get_current_user", lambda _request: "alice")

    task = SimpleNamespace(id="task-1", owner="alice", crew_member_id="crew-x")
    db = _FakeDb({_ScheduledTaskModel: [task], _CrewMemberModel: []})
    monkeypatch.setattr(assistant_routes, "SessionLocal", lambda: db)

    scheduler = _RunScheduler(started=True)
    router = assistant_routes.setup_assistant_routes(scheduler)
    run_now = _endpoint(router, "POST", "/api/assistant/run/{task_id}")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run_now("task-1", SimpleNamespace()))

    assert exc.value.status_code == 400
    assert scheduler.called_with == []


def test_run_now_starts_assistant_task_and_returns_scheduler_result(monkeypatch):
    _install_models(monkeypatch)
    monkeypatch.setattr(assistant_routes, "get_current_user", lambda _request: "alice")

    task = SimpleNamespace(id="task-1", owner="alice", crew_member_id="crew-1")
    crew = SimpleNamespace(id="crew-1", is_default_assistant=True)
    db = _FakeDb({_ScheduledTaskModel: [task], _CrewMemberModel: [crew]})
    monkeypatch.setattr(assistant_routes, "SessionLocal", lambda: db)

    scheduler = _RunScheduler(started=False)
    router = assistant_routes.setup_assistant_routes(scheduler)
    run_now = _endpoint(router, "POST", "/api/assistant/run/{task_id}")

    out = asyncio.run(run_now("task-1", SimpleNamespace()))

    assert out == {"started": False}
    assert scheduler.called_with == ["task-1"]
