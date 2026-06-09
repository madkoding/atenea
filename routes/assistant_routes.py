"""Personal assistant routes — resolve the per-user singleton, read/write
its settings, and list its scheduled check-in tasks.

The personal assistant is just a specially-flagged CrewMember that owns one
pinned Session and three daily ScheduledTasks ("Morning/Midday/Evening
check-in"). Everything about it is user-editable: name, personality, model,
enabled tools, timezone, and the three check-in times/prompts/enabled flags.
"""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.database import SessionLocal, CrewMember, ScheduledTask, utcnow_naive as _utcnow_naive
from src.auth.helpers import get_current_user
from src.scheduling.task_scheduler import compute_next_run


class CheckInUpdate(BaseModel):
    id: str                               # ScheduledTask.id
    name: str | None = None
    scheduled_time: str | None = None  # "HH:MM"
    prompt: str | None = None
    enabled: bool | None = None        # maps to status "active"/"paused"


class AssistantSettingsUpdate(BaseModel):
    name: str | None = None
    avatar: str | None = None
    personality: str | None = None
    model: str | None = None
    endpoint_url: str | None = None
    enabled_tools: list[str] | None = None
    allow_autonomous_email: bool | None = None  # convenience toggle
    timezone: str | None = None
    check_ins: list[CheckInUpdate] | None = None


_EMAIL_TOOLS = {"send_email", "reply_to_email"}





def _crew_to_dict(c: CrewMember) -> dict:
    tools = _decode_tools(c.enabled_tools)
    return {
        "id": c.id,
        "name": c.name,
        "avatar": c.avatar,
        "personality": c.personality,
        "model": c.model,
        "endpoint_url": c.endpoint_url,
        "greeting": c.greeting,
        "enabled_tools": tools,
        "session_id": c.session_id,
        "is_default_assistant": bool(c.is_default_assistant),
        "timezone": c.timezone,
        "allow_autonomous_email": any(t in _EMAIL_TOOLS for t in tools),
    }


def _decode_tools(raw_tools) -> list[str]:
    try:
        parsed = json.loads(raw_tools) if raw_tools else []
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _with_autonomous_email_toggle(tools: list[str], enabled: bool) -> list[str]:
    if enabled:
        for tool_name in _EMAIL_TOOLS:
            if tool_name not in tools:
                tools.append(tool_name)
        return tools
    return [tool_name for tool_name in tools if tool_name not in _EMAIL_TOOLS]


def _apply_checkin_update(task: ScheduledTask, check_in: CheckInUpdate, now_utc: datetime, tz_name: str | None) -> None:
    if check_in.name is not None:
        task.name = check_in.name.strip() or task.name
    time_changed = False
    if check_in.scheduled_time is not None and check_in.scheduled_time != task.scheduled_time:
        task.scheduled_time = check_in.scheduled_time
        time_changed = True
    if check_in.prompt is not None:
        task.prompt = check_in.prompt
    if check_in.enabled is not None:
        task.status = "active" if check_in.enabled else "paused"
    if time_changed or check_in.enabled is True:
        task.next_run = compute_next_run(
            task.schedule or "daily",
            task.scheduled_time,
            task.scheduled_day,
            task.scheduled_date,
            after=now_utc,
            cron_expression=task.cron_expression,
            tz_name=tz_name,
        )
    task.updated_at = _utcnow_naive()


def _recompute_task_next_run(task: ScheduledTask, now_utc: datetime, tz_name: str | None) -> None:
    if task.schedule and task.scheduled_time:
        task.next_run = compute_next_run(
            task.schedule,
            task.scheduled_time,
            task.scheduled_day,
            task.scheduled_date,
            after=now_utc,
            cron_expression=task.cron_expression,
            tz_name=tz_name,
        )


def _task_to_checkin_dict(t: ScheduledTask) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "scheduled_time": t.scheduled_time,
        "prompt": t.prompt,
        "enabled": (t.status or "active") == "active",
        "next_run": t.next_run.isoformat() + "Z" if t.next_run else None,
        "last_run": t.last_run.isoformat() + "Z" if t.last_run else None,
        "run_count": t.run_count or 0,
    }


def setup_assistant_routes(task_scheduler) -> APIRouter:
    router = APIRouter(prefix="/api/assistant", tags=["assistant"])

    def _owner(request: Request) -> str:
        owner = get_current_user(request)
        if not owner:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return owner

    # Synthetic / non-human owners that should NEVER get an assistant +
    # check-in tasks seeded. Hitting any /assistant route under one of these
    # used to seed a full CrewMember + Morning/Midday/Evening tasks under that
    # owner, which then double-fired alongside the real user's check-ins.
    _SYNTHETIC_OWNERS = frozenset({"internal-tool", "api", "demo", "system", ""})

    async def _get_or_create(owner: str) -> CrewMember:
        """Return the per-owner assistant CrewMember, creating it on demand."""
        if not owner or owner in _SYNTHETIC_OWNERS:
            raise HTTPException(status_code=400, detail=f"Cannot seed assistant for {owner!r}")
        db = SessionLocal()
        try:
            crew = db.query(CrewMember).filter(
                CrewMember.owner == owner,
                CrewMember.is_default_assistant == True,  # noqa: E712
            ).first()
            if crew:
                return crew
        finally:
            db.close()
        # Seed lazily. This is the same code the startup hook runs for each
        # user — safe to call again, it's idempotent.
        await task_scheduler.ensure_assistant_defaults(owner)
        db = SessionLocal()
        try:
            crew = db.query(CrewMember).filter(
                CrewMember.owner == owner,
                CrewMember.is_default_assistant == True,  # noqa: E712
            ).first()
            return crew
        finally:
            db.close()

    @router.get("/session")
    async def get_assistant_session(request: Request):
        """Resolve (or lazily create) the pinned Assistant session for this user."""
        owner = _owner(request)
        crew = await _get_or_create(owner)
        if not crew or not crew.session_id:
            raise HTTPException(status_code=500, detail="Assistant session could not be resolved")
        return {
            "session_id": crew.session_id,
            "crew_member_id": crew.id,
            "name": crew.name,
        }

    @router.get("/settings")
    async def get_assistant_settings(request: Request):
        """Return CrewMember fields + the three check-in task rows + task IDs for logs."""
        owner = _owner(request)
        crew = await _get_or_create(owner)
        if not crew:
            raise HTTPException(status_code=500, detail="Assistant not available")
        db = SessionLocal()
        try:
            tasks = db.query(ScheduledTask).filter(
                ScheduledTask.owner == owner,
                ScheduledTask.crew_member_id == crew.id,
            ).order_by(ScheduledTask.scheduled_time.asc()).all()
            return {
                "crew": _crew_to_dict(crew),
                "check_ins": [_task_to_checkin_dict(t) for t in tasks],
                "task_ids": [t.id for t in tasks],
            }
        finally:
            db.close()

    @router.patch("/settings")
    async def update_assistant_settings(payload: AssistantSettingsUpdate, request: Request):
        """Update CrewMember fields and/or check-in tasks in one call."""
        owner = _owner(request)
        crew = await _get_or_create(owner)
        if not crew:
            raise HTTPException(status_code=500, detail="Assistant not available")

        db = SessionLocal()
        try:
            crew_db = db.query(CrewMember).filter(CrewMember.id == crew.id).first()
            if not crew_db:
                raise HTTPException(status_code=404, detail="Assistant not found")

            # Update CrewMember fields.
            if payload.name is not None:
                crew_db.name = payload.name.strip() or crew_db.name
            if payload.avatar is not None:
                crew_db.avatar = payload.avatar
            if payload.personality is not None:
                crew_db.personality = payload.personality
            if payload.model is not None:
                crew_db.model = payload.model or None
            if payload.endpoint_url is not None:
                crew_db.endpoint_url = payload.endpoint_url or None
            if payload.timezone is not None:
                crew_db.timezone = payload.timezone or None

            # Tool list: either explicit list, or implicit toggle.
            if payload.enabled_tools is not None:
                crew_db.enabled_tools = json.dumps(payload.enabled_tools)
            if payload.allow_autonomous_email is not None:
                existing = _decode_tools(crew_db.enabled_tools)
                existing = _with_autonomous_email_toggle(existing, payload.allow_autonomous_email)
                crew_db.enabled_tools = json.dumps(existing)

            crew_db.updated_at = _utcnow_naive()

            # Update check-in tasks.
            if payload.check_ins:
                now_utc = _utcnow_naive()
                tz_name = crew_db.timezone or None
                for ci in payload.check_ins:
                    task = db.query(ScheduledTask).filter(
                        ScheduledTask.id == ci.id,
                        ScheduledTask.owner == owner,
                        ScheduledTask.crew_member_id == crew_db.id,
                    ).first()
                    if not task:
                        continue
                    _apply_checkin_update(task, ci, now_utc, tz_name)

            # Timezone change also shifts the NEXT run of all check-ins even if
            # the user didn't touch the time fields.
            if payload.timezone is not None:
                now_utc = _utcnow_naive()
                tz_name = crew_db.timezone or None
                tasks = db.query(ScheduledTask).filter(
                    ScheduledTask.owner == owner,
                    ScheduledTask.crew_member_id == crew_db.id,
                ).all()
                for t in tasks:
                    _recompute_task_next_run(t, now_utc, tz_name)

            db.commit()

            # Re-read crew_db + tasks to return the fresh state.
            crew_out = db.query(CrewMember).filter(CrewMember.id == crew.id).first()
            tasks_out = db.query(ScheduledTask).filter(
                ScheduledTask.owner == owner,
                ScheduledTask.crew_member_id == crew.id,
            ).order_by(ScheduledTask.scheduled_time.asc()).all()
            return {
                "crew": _crew_to_dict(crew_out),
                "check_ins": [_task_to_checkin_dict(t) for t in tasks_out],
                "task_ids": [t.id for t in tasks_out],
            }
        finally:
            db.close()

    @router.post("/run/{task_id}")
    async def run_check_in_now(task_id: str, request: Request):
        """Trigger one of the assistant's check-ins immediately (manual test)."""
        owner = _owner(request)
        db = SessionLocal()
        try:
            task = db.query(ScheduledTask).filter(
                ScheduledTask.id == task_id,
                ScheduledTask.owner == owner,
            ).first()
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            crew = db.query(CrewMember).filter(
                CrewMember.id == task.crew_member_id,
                CrewMember.is_default_assistant == True,  # noqa: E712
            ).first()
            if not crew:
                raise HTTPException(status_code=400, detail="Not an assistant task")
        finally:
            db.close()
        started = await task_scheduler.run_task_now(task_id)
        return {"started": bool(started)}

    @router.get("/run-status/{task_id}")
    async def run_status(task_id: str, request: Request):
        """Check whether the most recent run of a task has finished."""
        from core.database import TaskRun, ScheduledTask
        user = _owner(request)
        db = SessionLocal()
        try:
            # SECURITY: 404 if the task doesn't belong to this user — without
            # this any authenticated user could poll the status of any task_id.
            task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            if not task:
                raise HTTPException(404, "Task not found")
            if user and task.owner != user:
                raise HTTPException(404, "Task not found")
            run = db.query(TaskRun).filter(
                TaskRun.task_id == task_id,
            ).order_by(TaskRun.started_at.desc()).first()
            if not run:
                return {"status": "unknown"}
            if run.status == "running":
                return {"status": "running"}
            return {"status": "done", "result_status": run.status}
        finally:
            db.close()

    @router.get("/available-timezones")
    async def list_timezones():
        """Return the IANA tz name list used to populate the settings dropdown."""
        try:
            from zoneinfo import available_timezones
            zones = sorted(available_timezones())
        except Exception:
            zones = ["UTC"]
        return {"timezones": zones}

    return router
