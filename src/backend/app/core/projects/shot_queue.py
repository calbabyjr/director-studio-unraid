"""Sequential H3 production queue: run next / remaining shots."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from ..h3.submit import stage_voice_audio, submit_h3_shot
from ..jobs.store import load_job
from ..media.tail_frame import extract_clip_tail_frame
from ..paths import ensure_project_tree
from ..schemas import JobRecord, JobStatus
from .models import Shot, ShotStatus
from .store import list_shots, load_shot

logger = logging.getLogger("director_studio.shot_queue")

QueueMode = Literal["next", "remaining"]
QueueStatus = Literal["idle", "running", "failed"]
_ACTIVE_JOB = frozenset(
    {JobStatus.queued, JobStatus.uploading, JobStatus.running}
)
_SKIP_QUEUE_STATUSES = frozenset(
    {ShotStatus.succeeded, ShotStatus.queued, ShotStatus.running}
)


class ProductionQueue(BaseModel):
    project_id: str
    mode: QueueMode = "next"
    status: QueueStatus = "idle"
    current_shot_id: str | None = None
    current_job_id: str | None = None
    pending_shot_ids: list[str] = Field(default_factory=list)
    completed_shot_ids: list[str] = Field(default_factory=list)
    chain_tail_frames: bool = True
    error: str | None = None
    updated_at: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def queue_path(project_id: str):
    return ensure_project_tree(project_id) / "sequence" / "production_queue.json"


def load_queue(project_id: str) -> ProductionQueue:
    path = queue_path(project_id)
    if not path.is_file():
        return ProductionQueue(project_id=project_id, updated_at=_now())
    try:
        return ProductionQueue.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return ProductionQueue(project_id=project_id, updated_at=_now())


def save_queue(queue: ProductionQueue) -> ProductionQueue:
    queue.updated_at = _now()
    path = queue_path(queue.project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(queue.model_dump_json(indent=2), encoding="utf-8")
    return queue


def _ordered_shots(project_id: str) -> list[Shot]:
    return list_shots(project_id)


def _pending_ids(project_id: str, *, mode: QueueMode, from_shot_id: str | None) -> list[str]:
    shots = _ordered_shots(project_id)
    if not shots:
        return []
    start = 0
    if from_shot_id:
        start = next(
            (index for index, shot in enumerate(shots) if shot.id == from_shot_id),
            None,
        )
        if start is None:
            raise ValueError(f"shot not found: {from_shot_id}")
    ids = [
        shot.id
        for shot in shots[start:]
        if shot.status not in _SKIP_QUEUE_STATUSES
    ]
    if mode == "next":
        return ids[:1]
    return ids


async def start_production_queue(
    project_id: str,
    *,
    mode: QueueMode,
    from_shot_id: str | None = None,
    chain_tail_frames: bool = True,
    director_service: object | None = None,
) -> ProductionQueue:
    current = load_queue(project_id)
    if current.status == "running" and current.current_job_id:
        job = load_job(current.current_job_id)
        if job and job.status in _ACTIVE_JOB:
            raise ValueError(f"production queue already running ({job.id})")
    pending = _pending_ids(project_id, mode=mode, from_shot_id=from_shot_id)
    if not pending:
        raise ValueError("no shots to queue")
    queue = ProductionQueue(
        project_id=project_id,
        mode=mode,
        status="running",
        pending_shot_ids=pending,
        completed_shot_ids=[],
        chain_tail_frames=chain_tail_frames,
    )
    save_queue(queue)
    return await _advance_queue(queue, director_service=director_service)


def _chain_tail_frame(
    *,
    project_id: str,
    source_shot_id: str,
    target_shot_id: str,
    fallback_job_id: str,
) -> None:
    """Extract a tail frame from the pinned take, else the job that just succeeded."""
    source_shot = load_shot(project_id, source_shot_id)
    pinned_id = (source_shot.h3_job_id or "").strip() if source_shot else ""
    tried: set[str] = set()
    for source_job_id in (pinned_id, fallback_job_id):
        if not source_job_id or source_job_id in tried:
            continue
        tried.add(source_job_id)
        try:
            extract_clip_tail_frame(
                project_id=project_id,
                source_shot_id=source_shot_id,
                target_shot_id=target_shot_id,
                source_job_id=source_job_id,
            )
            return
        except Exception:
            logger.exception(
                "tail-frame chain failed %s → %s using %s",
                source_shot_id,
                target_shot_id,
                source_job_id,
            )


async def cancel_production_queue(project_id: str) -> ProductionQueue:
    """Idle the JSON queue, then cancel the in-flight H3 job if one is bound."""
    from ..jobs import cancel_job

    queue = load_queue(project_id)
    job_id = (queue.current_job_id or "").strip() or None
    queue.status = "idle"
    queue.current_shot_id = None
    queue.current_job_id = None
    queue.error = None
    saved = save_queue(queue)
    if job_id:
        try:
            await cancel_job(job_id)
        except Exception:
            logger.exception("failed to cancel in-flight H3 job %s", job_id)
    return saved


async def on_h3_job_terminal(job: JobRecord) -> None:
    project_id = str((job.params or {}).get("project_id") or job.project_id or "")
    if not project_id:
        return
    queue = load_queue(project_id)
    if queue.status != "running" or queue.current_job_id != job.id:
        return
    if job.status != JobStatus.succeeded:
        queue.status = "failed"
        queue.error = job.error or f"H3 job {job.status.value}"
        save_queue(queue)
        return
    if queue.current_shot_id and queue.current_shot_id not in queue.completed_shot_ids:
        queue.completed_shot_ids.append(queue.current_shot_id)
    remaining = [sid for sid in queue.pending_shot_ids if sid not in queue.completed_shot_ids]
    queue.pending_shot_ids = remaining
    if queue.mode == "next" or not remaining:
        queue.status = "idle"
        queue.current_shot_id = None
        queue.current_job_id = None
        save_queue(queue)
        return
    next_id = remaining[0]
    if queue.chain_tail_frames and queue.current_shot_id:
        _chain_tail_frame(
            project_id=project_id,
            source_shot_id=queue.current_shot_id,
            target_shot_id=next_id,
            fallback_job_id=job.id,
        )
    queue.current_shot_id = None
    queue.current_job_id = None
    save_queue(queue)
    await _advance_queue(queue)


async def _advance_queue(
    queue: ProductionQueue,
    *,
    director_service: object | None = None,
) -> ProductionQueue:
    while queue.pending_shot_ids:
        shot_id = queue.pending_shot_ids[0]
        shot = load_shot(queue.project_id, shot_id)
        if shot is None:
            queue.pending_shot_ids.pop(0)
            continue
        try:
            updated = await queue_h3_shot(
                shot,
                director_service=director_service,
            )
        except Exception as exc:
            logger.exception("queue could not submit %s", shot_id)
            queue.status = "failed"
            queue.error = str(exc)
            return save_queue(queue)
        queue.current_shot_id = updated.id
        queue.current_job_id = updated.h3_job_id
        queue.status = "running"
        queue.error = None
        return save_queue(queue)
    queue.status = "idle"
    queue.current_shot_id = None
    queue.current_job_id = None
    return save_queue(queue)


def _collect_voice_audio(shot: Shot) -> dict[str, tuple[str, bytes]]:
    """Stage H3-ready Voice files in audio_index order."""
    return stage_voice_audio(shot)


async def queue_h3_shot(
    shot: Shot,
    *,
    skip_prompt_refresh: bool = False,
    director_service: object | None = None,
    start_job=None,
) -> Shot:
    """Queue one H3 job through the shared submit path."""
    return await submit_h3_shot(
        shot,
        director_service=director_service,
        queued_by="production_queue",
        skip_prompt_refresh=skip_prompt_refresh,
        start_job=start_job,
    )
