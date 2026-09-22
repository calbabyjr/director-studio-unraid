"""Periodic memory check: each director rereads TASKS.md and memory for open work."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from ...config import settings
from ..schemas import JobStatus
from ..souls.store import resolve_soul_id
from ..workspace.store import get_file, save_file
from ..workspace.templates import PROJECT_TASKS_TEMPLATE, TASKS_FILENAME
from .chat_history import append_chat_message
from .chat_sessions import director_chat_sessions
from .director_learning import read_memory_md
from .director_memory import load_notes
from .models import ShotStatus
from .store import list_projects, list_shots

logger = logging.getLogger("director_studio.director.patrol")

OPEN_SHOT_STATUSES = {
    ShotStatus.failed,
    ShotStatus.blocked,
    ShotStatus.needs_review,
}
_OPEN_CHECKBOX = re.compile(r"^\s*[-*]\s+\[[ \t]?\][ \t]+(\S(?:[^\n]*\S)?)\s*$", re.MULTILINE)
_TASKISH = re.compile(
    r"\b(todo|to-do|need to|still need|remember to|follow up|don't forget|pending task)\b",
    re.I,
)
_BULLET = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)
MESSAGE_PREFIX = "Memory check —"


class OpenTask(BaseModel):
    source: str
    text: str
    project_id: str
    soul_id: str


class ProjectPatrolResult(BaseModel):
    project_id: str
    soul_id: str
    tasks: list[str] = Field(default_factory=list)
    posted: bool = False
    skipped: str | None = None


class PatrolReport(BaseModel):
    ran_at: str
    next_at: str | None = None
    projects: list[ProjectPatrolResult] = Field(default_factory=list)


def patrol_state_path() -> Path:
    path = settings.data_dir / "patrol.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _load_state() -> dict:
    path = patrol_state_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_state(state: dict) -> None:
    patrol_state_path().write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _task_hash(texts: list[str]) -> str:
    blob = "\n".join(sorted(texts)).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def open_checkbox_items(markdown: str) -> list[str]:
    return [_normalize(match.group(1)) for match in _OPEN_CHECKBOX.finditer(markdown or "")]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _taskish_lines(markdown: str) -> list[str]:
    found: list[str] = []
    for match in _BULLET.finditer(markdown or ""):
        line = _normalize(match.group(1))
        if _OPEN_CHECKBOX.match(f"- {line}"):
            continue
        if line.lower().startswith("[x]"):
            continue
        if _TASKISH.search(line) and len(line) >= 8:
            found.append(line)
    return found


def sync_board_tasks_file(project_id: str) -> list[str]:
    """Write production TASKS.md from shots that still need prompt or H3 video."""
    lines: list[str] = []
    for shot in list_shots(project_id):
        title = shot.title or shot.id
        status = shot.status if isinstance(shot.status, ShotStatus) else ShotStatus(str(shot.status))
        prompt = shot.prompt_sections
        has_prompt = bool(prompt and str(getattr(prompt, "summary", "") or "").strip())
        if status == ShotStatus.succeeded and shot.h3_job_id:
            continue
        if not has_prompt:
            lines.append(f"Write the H3 prompt for {title}")
        elif status in {
            ShotStatus.needs_review,
            ShotStatus.approved,
            ShotStatus.ref_frame_pending,
            ShotStatus.draft,
            ShotStatus.planning,
        }:
            lines.append(f"Generate H3 video for {title}")
        elif status in {ShotStatus.failed, ShotStatus.blocked}:
            lines.append(f"Fix {title} ({status.value})")
    body = PROJECT_TASKS_TEMPLATE.rstrip() + "\n"
    if lines:
        body += "\n" + "\n".join(f"- [ ] {line}" for line in lines) + "\n"
    save_file(TASKS_FILENAME, body, scope="project", project_id=project_id)
    return lines


def collect_open_tasks(project_id: str, soul_id: str | None = None) -> list[OpenTask]:
    slug = resolve_soul_id(soul_id, project_id)
    tasks: list[OpenTask] = []
    seen: set[str] = set()

    def add(source: str, text: str) -> None:
        clipped = _normalize(text)
        key = clipped.lower()
        if len(clipped) < 8 or key in seen:
            return
        seen.add(key)
        tasks.append(OpenTask(source=source, text=clipped, project_id=project_id, soul_id=slug))

    director_tasks = get_file(TASKS_FILENAME, "global", project_id=project_id, soul_id=slug)
    if director_tasks is not None:
        for item in open_checkbox_items(director_tasks.markdown):
            add("director TASKS.md", item)
    project_tasks = get_file(TASKS_FILENAME, "project", project_id=project_id, soul_id=slug)
    if project_tasks is not None:
        for item in open_checkbox_items(project_tasks.markdown):
            add("production TASKS.md", item)

    for markdown in (
        read_memory_md("global", project_id, slug),
        read_memory_md("project", project_id, slug),
    ):
        for item in open_checkbox_items(markdown):
            add("MEMORY.md", item)
        for item in _taskish_lines(markdown):
            add("MEMORY.md", item)
    for note in load_notes(project_id, slug):
        if _TASKISH.search(note.text):
            add("standing note", note.text)

    for shot in list_shots(project_id):
        status = shot.status if isinstance(shot.status, ShotStatus) else ShotStatus(str(shot.status))
        title = shot.title or shot.id
        if status in OPEN_SHOT_STATUSES:
            add("shot", f"{title} is {status.value}")
        if shot.meta.get("material_review_pending") is True:
            add("shot", f"{title} still needs Picture review")

    from ..jobs.store import list_jobs

    for job in list_jobs(limit=200, project_id=project_id):
        if job.status == JobStatus.failed:
            add("job", f"{job.name or job.id} failed ({job.pipeline_id})")
    return tasks


def format_patrol_message(tasks: list[OpenTask]) -> str:
    count = len(tasks)
    noun = "task" if count == 1 else "tasks"
    lines = [f"{MESSAGE_PREFIX} I still have {count} open {noun}:", ""]
    for task in tasks[:12]:
        lines.append(f"- {task.text} ({task.source})")
    if count > 12:
        lines.append(f"- …and {count - 12} more")
    lines.append("")
    lines.append("I did not queue generation. Tell me which item to work next.")
    return "\n".join(lines)


def patrol_project(project_id: str) -> ProjectPatrolResult:
    from .store import load_project

    project = load_project(project_id)
    if project is None:
        return ProjectPatrolResult(project_id=project_id, soul_id="studio", skipped="missing")
    soul_id = resolve_soul_id(getattr(project, "soul_id", None), project_id)
    result = ProjectPatrolResult(project_id=project_id, soul_id=soul_id)
    if director_chat_sessions.is_active(project_id):
        result.skipped = "chat_active"
        return result
    sync_board_tasks_file(project_id)
    tasks = collect_open_tasks(project_id, soul_id)
    result.tasks = [task.text for task in tasks]
    if not tasks:
        return result
    digest = _task_hash(result.tasks)
    state = _load_state()
    projects = state.setdefault("projects", {})
    previous = projects.get(project_id) or {}
    if previous.get("task_hash") == digest:
        result.skipped = "unchanged"
        return result
    append_chat_message(project_id, role="assistant", content=format_patrol_message(tasks))
    projects[project_id] = {
        "task_hash": digest,
        "posted_at": _now_iso(),
        "count": len(tasks),
        "soul_id": soul_id,
    }
    _save_state(state)
    result.posted = True
    return result


def run_patrol() -> PatrolReport:
    interval = max(60, int(getattr(settings, "director_memory_check_sec", 1800) or 1800))
    ran_at = _now()
    report = PatrolReport(
        ran_at=ran_at.isoformat(),
        next_at=(ran_at + timedelta(seconds=interval)).isoformat(),
    )
    for project in list_projects():
        try:
            report.projects.append(patrol_project(project.id))
        except Exception:
            logger.exception("memory patrol failed for %s", project.id)
            report.projects.append(
                ProjectPatrolResult(
                    project_id=project.id,
                    soul_id=getattr(project, "soul_id", None) or "studio",
                    skipped="error",
                )
            )
    state = _load_state()
    state["last_run_at"] = report.ran_at
    state["next_at"] = report.next_at
    _save_state(state)
    posted = sum(1 for item in report.projects if item.posted)
    logger.info(
        "memory patrol finished projects=%s posted=%s",
        len(report.projects),
        posted,
    )
    return report


def patrol_status() -> dict:
    state = _load_state()
    return {
        "enabled": bool(getattr(settings, "director_memory_check_enabled", True)),
        "interval_sec": max(60, int(getattr(settings, "director_memory_check_sec", 1800) or 1800)),
        "last_run_at": state.get("last_run_at"),
        "next_at": state.get("next_at"),
        "projects": state.get("projects") or {},
    }


async def memory_patrol_loop(*, fire_immediately: bool = False) -> None:
    interval = max(60, int(getattr(settings, "director_memory_check_sec", 1800) or 1800))
    if not fire_immediately:
        await asyncio.sleep(interval)
    while True:
        if getattr(settings, "director_memory_check_enabled", True):
            try:
                run_patrol()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("memory patrol loop failed")
            try:
                from .director_reflection import drain_pending_reflections

                await drain_pending_reflections()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("director reflection drain failed")
        await asyncio.sleep(interval)
