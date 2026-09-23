"""Backend-owned Picture review for Shots flagged material_review_pending.

The flag is only cleared by DirectorService.write_prompts_after_layout. Relying
on the Director agent to call write_prompt left Shots stuck on "Prompt needs
refresh" whenever the model answered in prose instead of a tool call, so the
backend runs the review itself once a flagged Shot has been idle for a while.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..schemas import JobStatus
from .chat_sessions import director_chat_sessions
from .models import Shot, ShotStatus
from .store import list_projects, list_shots, shots_dir

logger = logging.getLogger("director_studio.director.material_review_worker")

LOOP_INTERVAL_SEC = 120
# Let the user finish adding/removing Pictures before reviewing.
IDLE_SEC = 90

_review_lock = asyncio.Lock()
RETRY_BACKOFF_SEC = 600

# shot_id -> shot file mtime when a review that failed on the Shot's own content
# started; retried only after the Shot changes again, never in a tight loop.
_failed_at_mtime: dict[str, float] = {}
# shot_id -> time before which a transiently failed review is not retried.
_retry_after: dict[str, float] = {}


def _transient_review_failure(exc: Exception) -> bool:
    """GPU/LLM hiccups and edits made mid-review are retried after a backoff."""
    import httpx

    from ..vram.orchestrator import GPUBusyError

    if isinstance(exc, (GPUBusyError, httpx.HTTPError, TimeoutError, ConnectionError)):
        return True
    return "review again" in str(exc)


def _shot_mtime(shot: Shot) -> float:
    try:
        return (shots_dir(shot.project_id) / f"{shot.id}.json").stat().st_mtime
    except OSError:
        return 0.0


def _video_active(shot: Shot) -> bool:
    if shot.status in {ShotStatus.queued, ShotStatus.running}:
        return True
    if not shot.h3_job_id:
        return False
    from ..jobs.store import load_job

    job = load_job(shot.h3_job_id)
    return bool(job and job.status in {JobStatus.queued, JobStatus.uploading, JobStatus.running})


def _default_service():
    from ...agents.director.llm_plan_provider import DirectorLLMPlanProvider
    from ...agents.director.service import DirectorService

    return DirectorService(plan_provider=DirectorLLMPlanProvider())


async def refresh_shot_review(shot_id: str, project_id: str, svc=None) -> Shot:
    """Run the full Picture review + prompt decision for one Shot now."""
    svc = svc or _default_service()
    async with _review_lock:
        shot = await svc.write_prompts_after_layout(shot_id)
    _failed_at_mtime.pop(shot_id, None)
    _retry_after.pop(shot_id, None)
    logger.info(
        "material review done for %s/%s pending=%s",
        project_id, shot_id, (shot.meta or {}).get("material_review_pending"),
    )
    return shot


def _due_shots() -> list[Shot]:
    now = time.time()
    due: list[Shot] = []
    for project in list_projects():
        if director_chat_sessions.is_active(project.id):
            continue
        for shot in list_shots(project.id):
            if (shot.meta or {}).get("material_review_pending") is not True:
                continue
            mtime = _shot_mtime(shot)
            if now - mtime < IDLE_SEC or _failed_at_mtime.get(shot.id) == mtime:
                continue
            if now < _retry_after.get(shot.id, 0.0):
                continue
            if _video_active(shot):
                continue
            due.append(shot)
    return due


async def refresh_pending_reviews(svc=None) -> list[str]:
    """Review every idle flagged Shot once; returns the Shot ids cleared."""
    from ..vram import get_orchestrator

    cleared: list[str] = []
    for shot in _due_shots():
        # Re-check just before each review: a batch can take many minutes, and
        # a user generation or chat may have started meanwhile.
        if await get_orchestrator().llm_blocking_reservations():
            break
        if director_chat_sessions.is_active(shot.project_id):
            continue
        started_mtime = _shot_mtime(shot)
        try:
            done = await refresh_shot_review(shot.id, shot.project_id, svc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _transient_review_failure(exc):
                _retry_after[shot.id] = time.time() + RETRY_BACKOFF_SEC
            else:
                # Keyed on the pre-review mtime so an edit made during the
                # review makes the Shot due again.
                _failed_at_mtime[shot.id] = started_mtime
            logger.warning("material review failed for %s: %s", shot.id, exc)
            continue
        if (done.meta or {}).get("material_review_pending") is not True:
            cleared.append(shot.id)
    return cleared


async def material_review_loop(interval: int = LOOP_INTERVAL_SEC) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await refresh_pending_reviews()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("material review loop failed")
