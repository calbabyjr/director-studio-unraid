"""Rebuild an existing Actor asset sheet from its attached stills."""

from __future__ import annotations

from pathlib import Path

from ...pipelines.actor.workflow import (
    DRESS_CLOTHED,
    DRESS_UNCLOTHED,
    derive_mode,
    dress_state_prompt,
    normalize_dress_state,
)
from ..jobs import create_job, start_pipeline_job
from ..paths import find_asset_dir
from ..projects.takes import pin_actor_take
from ..schemas import JobRecord, JobStatus, LibraryAsset
from .store import load_asset, write_asset

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PRIMARY_KEYS = ("input_actor", "actor", "master", "fullbody_threeview")
EXTRA_KEYS = ("face", "profile", "back", "threeview_extra")
# Only a human-uploaded wardrobe still. Generated wardrobe_ref would re-dress a nude actor.
WARDROBE_KEYS = ("input_wardrobe",)
PRESERVE_DRESS_DESCRIPTION = (
    "Preserve the body exactly as photographed in the reference stills, "
    "including fully nude or barefoot when that is how they appear. "
    "Do not add clothing, lingerie, towels, drapes, or studio wear. "
    "Do not invent an outfit."
)


def pack_actor_sheet_images(actor: LibraryAsset) -> dict[str, tuple[str, bytes]]:
    adir = find_asset_dir("actors", actor.id)
    if adir is None:
        raise ValueError("actor files not found")
    files = dict(actor.files or {})

    def read(key: str) -> tuple[str, bytes] | None:
        name = files.get(key)
        if not name:
            return None
        path = adir / name
        if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
            return None
        return name, path.read_bytes()

    images: dict[str, tuple[str, bytes]] = {}
    used: set[str] = set()
    for key in PRIMARY_KEYS:
        hit = read(key)
        if hit is None:
            continue
        images["actor"] = hit
        used.add(key)
        break
    for key in EXTRA_KEYS:
        if key in used:
            continue
        hit = read(key)
        if hit is not None:
            images[key] = hit
    for key in WARDROBE_KEYS:
        hit = read(key)
        if hit is not None:
            images["wardrobe"] = hit
            break
    if "actor" not in images:
        for key in EXTRA_KEYS:
            if key in images:
                images["actor"] = images.pop(key)
                break
    if "actor" not in images:
        raise ValueError("add at least one still before updating the asset sheet")
    return images


async def queue_actor_sheet_update(
    actor_id: str,
    *,
    dress_state: str | None = None,
) -> JobRecord:
    actor = load_asset("actors", actor_id)
    if actor is None:
        raise ValueError(f"actor not found: {actor_id}")
    dress = normalize_dress_state(
        dress_state or (actor.meta or {}).get("dress_state") or DRESS_UNCLOTHED
    )
    images = pack_actor_sheet_images(actor)
    if dress != DRESS_CLOTHED:
        images.pop("wardrobe", None)
    extras = [key for key in EXTRA_KEYS if key in images]
    has_actor = True
    has_wardrobe = "wardrobe" in images
    notes = (actor.notes or "").strip()
    description = " ".join(
        part
        for part in (notes, dress_state_prompt(dress), PRESERVE_DRESS_DESCRIPTION)
        if part
    ).strip()
    job = create_job(
        pipeline_id="actor",
        asset_kind="actors",
        name=actor.name,
        notes=actor.notes,
        params={
            "description": description,
            "has_actor_ref": has_actor,
            "has_wardrobe_ref": has_wardrobe,
            "include_headwear": False,
            "include_footwear": False,
            "dress_state": dress,
            "extra_ref_keys": extras,
            "mode": derive_mode(has_actor_ref=has_actor, has_wardrobe_ref=has_wardrobe),
            "update_asset_id": actor.id,
            "actor_id": actor.id,
        },
        project_id=actor.project_id,
    )
    job.library_asset_id = actor.id
    from ..jobs.store import save_job

    save_job(job)
    meta = dict(actor.meta or {})
    meta["sheet_update_job_id"] = job.id
    meta["dress_state"] = dress
    write_asset(actor.model_copy(update={"meta": meta}))
    return await start_pipeline_job(job, images=images)


def apply_actor_sheet_update(job: JobRecord) -> LibraryAsset | None:
    if job.pipeline_id != "actor" or job.status != JobStatus.succeeded:
        return None
    target = str((job.params or {}).get("update_asset_id") or "")
    if not target:
        return None
    return pin_actor_take(target, job.id)
