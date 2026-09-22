"""Pin a generation take as the canonical actor sheet or H3 clip."""

from __future__ import annotations

import shutil

from ..jobs.store import list_jobs, load_job
from ..library.store import load_asset, write_asset
from ..media.clip_generations import list_shot_h3_generations
from ..paths import asset_write_dir, find_job_dir
from ..schemas import JobRecord, JobStatus
from .models import ShotStatus
from .store import load_shot, save_shot


def list_h3_takes(project_id: str, shot_id: str) -> list[JobRecord]:
    return list(reversed(list_shot_h3_generations(project_id, shot_id)))


def pin_h3_take(project_id: str, shot_id: str, job_id: str):
    shot = load_shot(project_id, shot_id)
    if shot is None:
        raise ValueError(f"shot not found: {shot_id}")
    job = load_job(job_id)
    if job is None or job.pipeline_id != "h3_ref2va":
        raise ValueError(f"H3 take not found: {job_id}")
    if (job.params or {}).get("shot_id") != shot_id:
        raise ValueError("take does not belong to this shot")
    if job.status != JobStatus.succeeded:
        raise ValueError("only a succeeded take can be pinned")
    updated = shot.model_copy(update={"h3_job_id": job.id, "status": ShotStatus.succeeded})
    save_shot(updated)
    return updated


def list_actor_takes(actor_id: str) -> list[JobRecord]:
    jobs = list_jobs(limit=None, pipeline_id="actor")
    matched = [
        job
        for job in jobs
        if job.library_asset_id == actor_id
        or (job.params or {}).get("actor_id") == actor_id
        or (job.params or {}).get("update_asset_id") == actor_id
    ]
    return matched


def pin_actor_take(actor_id: str, job_id: str):
    actor = load_asset("actors", actor_id)
    if actor is None:
        raise ValueError(f"actor not found: {actor_id}")
    job = load_job(job_id)
    if job is None or job.pipeline_id != "actor":
        raise ValueError(f"actor take not found: {job_id}")
    if job.status != JobStatus.succeeded:
        raise ValueError("only a succeeded take can be pinned")
    job_root = find_job_dir(job.id)
    if job_root is None:
        raise ValueError("take files are missing")
    outputs = job_root / "outputs"
    adir = asset_write_dir("actors", actor.id, project_id=actor.project_id)
    adir.mkdir(parents=True, exist_ok=True)
    files = dict(actor.files or {})
    for key, slot in (job.outputs or {}).items():
        name = getattr(slot, "filename", None) or f"{key}.png"
        src = outputs / name
        if not src.is_file():
            continue
        shutil.copy2(src, adir / name)
        files[key] = name
    meta = dict(actor.meta or {})
    meta["pinned_take_job_id"] = job.id
    return write_asset(actor.model_copy(update={"files": files, "meta": meta, "job_id": job.id}))
