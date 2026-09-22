"""Reflect on jobs, failed tools, and H3 clips; write new Director lessons."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ...config import settings
from ..schemas import JobRecord, JobStatus
from ..souls.store import record_soul_lesson, resolve_soul_id
from .director_learning import read_memory_md
from .director_memory import add_note, load_notes

logger = logging.getLogger("director_studio.director.reflection")

_PENDING: list[ReflectionEvent] = []
_PENDING_LIMIT = 16

Scope = Literal["project", "soul"]

_JSON_OBJECT_HINT = re.compile(r"json object|model_type|input_type=str", re.I)
_TAIL_HINT = re.compile(r"tail changed|last Shot|expected_last_shot_id", re.I)
_CLAIMED_QUEUE = re.compile(r"queued|queue it", re.I)


class ReflectionEvent(BaseModel):
    kind: Literal["job", "tool_failed", "h3_clip"]
    project_id: str | None = None
    pipeline_id: str = ""
    job_id: str = ""
    job_name: str = ""
    status: str = ""
    error: str = ""
    tool_name: str = ""
    shot_title: str = ""


class CraftLesson(BaseModel):
    text: str
    scope: Scope = "project"


class LLMLessonBatch(BaseModel):
    lessons: list[CraftLesson] = Field(default_factory=list)


def _clip(text: str, limit: int = 180) -> str:
    body = re.sub(r"\s+", " ", (text or "").strip())
    if len(body) <= limit:
        return body
    return body[: max(0, limit - 1)].rstrip() + "…"


def _existing_texts(project_id: str | None) -> set[str]:
    if not project_id:
        return set()
    corpus = "\n".join(
        [
            read_memory_md("global", project_id),
            read_memory_md("project", project_id),
            "\n".join(note.text for note in load_notes(project_id)),
        ]
    ).lower()
    return {line.strip() for line in corpus.splitlines() if len(line.strip()) >= 8}


def deterministic_lessons(event: ReflectionEvent) -> list[CraftLesson]:
    lessons: list[CraftLesson] = []
    if event.kind == "tool_failed":
        err = event.error or ""
        name = event.tool_name or "tool"
        if name == "append_shot" and _JSON_OBJECT_HINT.search(err):
            lessons.append(
                CraftLesson(
                    text="Pass append_shot.shot as a JSON object, never a string.",
                    scope="soul",
                )
            )
        elif name == "append_shot" and _TAIL_HINT.search(err):
            lessons.append(
                CraftLesson(
                    text="Refresh expected_last_shot_id from PROJECT_STATE before append_shot.",
                    scope="soul",
                )
            )
        else:
            lessons.append(
                CraftLesson(
                    text=_clip(
                        f"After {name} fails ({err or 'unknown error'}), do not claim the work saved."
                    ),
                    scope="soul",
                )
            )
    elif event.status == JobStatus.failed.value:
        pipeline = event.pipeline_id or "generation"
        err = event.error or "unknown error"
        lessons.append(
            CraftLesson(
                text=_clip(
                    f"When {pipeline} fails with {err}, fix that cause before retrying the same shot."
                ),
                scope="soul",
            )
        )
        lessons.append(
            CraftLesson(
                text="Never tell the user a job queued unless a job_ id exists.",
                scope="soul",
            )
        )
    elif event.kind in {"job", "h3_clip"} and event.status == JobStatus.succeeded.value:
        title = event.shot_title or event.job_name or "this shot"
        if (event.pipeline_id or "") in {"h3_ref2va", ""} or event.kind == "h3_clip":
            lessons.append(
                CraftLesson(
                    text=_clip(
                        f"{title} H3 succeeded. Keep those Picture bindings unless the user recasts."
                    ),
                    scope="project",
                )
            )
        else:
            lessons.append(
                CraftLesson(
                    text=_clip(
                        f"{event.pipeline_id or 'Job'} succeeded for {title}. Reuse that setup on retry."
                    ),
                    scope="project",
                )
            )
    return lessons


def commit_lessons(
    project_id: str | None,
    lessons: list[CraftLesson],
    *,
    source: str = "auto",
) -> list[str]:
    written: list[str] = []
    existing = _existing_texts(project_id)
    soul_id = resolve_soul_id(project_id=project_id) if project_id else None
    for lesson in lessons:
        text = _clip(lesson.text, 240)
        if len(text) < 8:
            continue
        key = text.lower()
        if key in existing or any(key in item or item in key for item in existing if item):
            continue
        existing.add(key)
        if lesson.scope == "soul" and soul_id:
            record_soul_lesson(soul_id, text, source=source)
            add_note(
                text=text,
                scope="global",
                source=source,  # type: ignore[arg-type]
                project_id=project_id,
                soul_id=soul_id,
            )
        elif project_id:
            add_note(
                text=text,
                scope="project",
                source=source,  # type: ignore[arg-type]
                project_id=project_id,
                soul_id=soul_id,
            )
        else:
            continue
        written.append(text)
    return written


def _llm_available() -> bool:
    if not getattr(settings, "director_reflect_with_llm", True):
        return False
    try:
        from ..vram import get_orchestrator

        orch = get_orchestrator()
    except Exception:
        return False
    if getattr(orch, "owner", None) == "comfy":
        return False
    return bool(getattr(orch, "_llm_ready", False))


def _chat_busy(project_id: str | None) -> bool:
    if not project_id:
        return False
    try:
        from .chat_sessions import director_chat_sessions

        return director_chat_sessions.is_active(project_id)
    except Exception:
        return False


def _event_brief(event: ReflectionEvent) -> str:
    return json.dumps(event.model_dump(), ensure_ascii=False)[:1200]


async def llm_invent_lessons(event: ReflectionEvent) -> list[CraftLesson]:
    if not _llm_available() or _chat_busy(event.project_id):
        return []
    standing = ""
    if event.project_id:
        standing = "\n".join(sorted(_existing_texts(event.project_id))[:24])
    prompt = (
        "Standing notes already stored:\n"
        f"{standing or '(none)'}\n\n"
        "Event:\n"
        f"{_event_brief(event)}\n\n"
        "Invent 1-3 new craft lessons grounded in that event."
    )
    system = (
        "You write durable Director lessons after production work. "
        'Return JSON only: {"lessons":[{"text":"...","scope":"project"|"soul"}]}. '
        "Each text under 180 characters. scope=soul follows this director to the next film. "
        "scope=project is this production only. Do not repeat standing notes. "
        "Do not invent people or shots absent from the event."
    )
    try:
        from ...core.llm import get_llm_provider
        from ...core.vram import get_director_model

        provider = get_llm_provider()
        model = str(get_director_model() or provider.model_status().get("model") or "").strip()
        raw = await provider.client.generate(
            model,
            f"{system}\n\n{prompt}",
            format="json",
            think=False,
        )
    except Exception:
        logger.exception("director LLM reflection failed")
        return []
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        batch = LLMLessonBatch.model_validate(payload)
    except Exception:
        logger.info("director LLM reflection returned unusable JSON")
        return []
    out: list[CraftLesson] = []
    for lesson in batch.lessons[:3]:
        text = _clip(lesson.text, 180)
        if len(text) >= 8:
            out.append(CraftLesson(text=text, scope=lesson.scope if lesson.scope in {"project", "soul"} else "project"))
    return out


def reflect_on_event(event: ReflectionEvent, *, allow_llm: bool = True) -> list[str]:
    """Deterministic lessons now; optional LLM invention when the GPU is free."""
    if not getattr(settings, "director_reflect_on_jobs", True):
        return []
    written = commit_lessons(event.project_id, deterministic_lessons(event), source="auto")
    if allow_llm:
        schedule_llm_reflection(event)
    return written


def schedule_llm_reflection(event: ReflectionEvent) -> None:
    if not _llm_available() or _chat_busy(event.project_id):
        _PENDING.append(event)
        if len(_PENDING) > _PENDING_LIMIT:
            del _PENDING[:-_PENDING_LIMIT]
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _PENDING.append(event)
        return
    loop.create_task(_llm_reflect_task(event))


async def drain_pending_reflections() -> None:
    if not _PENDING or not _llm_available():
        return
    events = list(_PENDING)
    _PENDING.clear()
    for event in events:
        if _chat_busy(event.project_id):
            _PENDING.append(event)
            continue
        await _llm_reflect_task(event)


async def _llm_reflect_task(event: ReflectionEvent) -> None:
    try:
        invented = await llm_invent_lessons(event)
        if invented:
            commit_lessons(event.project_id, invented, source="auto")
    except Exception:
        logger.exception("director reflection task failed")


def reflect_on_job(job: JobRecord) -> list[str]:
    if job.status not in {JobStatus.succeeded, JobStatus.failed}:
        return []
    params = job.params or {}
    event = ReflectionEvent(
        kind="h3_clip" if job.pipeline_id == "h3_ref2va" else "job",
        project_id=job.project_id,
        pipeline_id=job.pipeline_id,
        job_id=job.id,
        job_name=job.name,
        status=job.status.value,
        error=(job.error or "")[:400],
        shot_title=str(params.get("shot_title") or params.get("shot_id") or ""),
    )
    return reflect_on_event(event)


def reflect_on_tool_failure(
    *,
    project_id: str,
    tool_name: str,
    error: str,
) -> list[str]:
    event = ReflectionEvent(
        kind="tool_failed",
        project_id=project_id,
        tool_name=tool_name,
        error=(error or "")[:400],
        status="failed",
    )
    return reflect_on_event(event)
