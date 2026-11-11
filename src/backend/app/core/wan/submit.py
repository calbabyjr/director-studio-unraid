"""Queue a Wan clip from the shot's layout still and action."""

from __future__ import annotations

import logging
from typing import Any

from ...config import settings
from ..h3.submit import H3SubmitError
from ..jobs import create_job
from ..jobs.runner import start_pipeline_job
from ..library.images import resolve_asset_image
from ..library.store import load_asset
from ..projects.models import Shot, ShotStatus
from ..projects.store import load_shot, save_shot
from ..schemas import JobStatus

logger = logging.getLogger("director_studio.wan")


def motion_prompt(shot: Shot) -> str:
    """The sequence Wan should play, starting from the layout still."""
    sections = shot.prompt_sections
    parts = [
        (shot.script_beat or "").strip(),
        (sections.detailed_description or "").strip(),
        (sections.summary or "").strip(),
    ]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    if not seen:
        raise ValueError(
            "Write the shot action before submitting to Wan. "
            "The layout still is the opening frame; the action is the motion."
        )
    return "\n\n".join(seen)


def layout_still(shot: Shot) -> tuple[str, bytes]:
    asset_id = (shot.layout_asset_id or "").strip()
    if not asset_id:
        raise ValueError(
            "Wan needs a layout still. Generate a layout study and base the shot on it first."
        )
    asset = load_asset("layouts", asset_id)
    if asset is None:
        for kind in ("scenes", "actors", "props", "costumes"):
            asset = load_asset(kind, asset_id)
            if asset is not None:
                break
    if asset is None:
        raise ValueError(f"Layout still not found: {asset_id}")
    hit = resolve_asset_image(asset, role="layout_ref_frame")
    if not hit:
        raise ValueError(f"Layout still has no image file: {asset_id}")
    name, data, _key = hit
    return name, data


async def submit_wan_shot(shot: Shot) -> Shot:
    """Queue Wan image-to-video. Does not send the cast as separate pictures."""
    if shot.status in (ShotStatus.queued, ShotStatus.running):
        raise H3SubmitError(f"shot already {shot.status.value}", status_code=409)
    if shot.h3_job_id:
        from ..jobs import load_job

        existing = load_job(shot.h3_job_id)
        if existing and existing.status in (
            JobStatus.queued,
            JobStatus.uploading,
            JobStatus.running,
        ):
            raise H3SubmitError(
                f"Video job already active: {shot.h3_job_id} ({existing.status.value})",
                status_code=409,
            )

    prompt = motion_prompt(shot)
    filename, data = layout_still(shot)
    params: dict[str, Any] = {
        "prompt": prompt,
        "frames": 81,
        "width": 832,
        "height": 480,
        "image_keys": ["layout"],
        "shot_id": shot.id,
        "project_id": shot.project_id,
        "layout_asset_id": shot.layout_asset_id,
        "video_backend": "wan",
        "h3_provider": "local",
        "wan_high_unet": settings.wan_high_unet,
        "wan_low_unet": settings.wan_low_unet,
        "wan_clip": settings.wan_clip,
        "wan_vae": settings.wan_vae,
        "output_prefix": f"wan-director-studio/{shot.project_id}/{shot.id}",
    }
    job = create_job(
        pipeline_id="wan_i2v",
        asset_kind="productions",
        name=f"wan:{shot.title}",
        notes=shot.script_beat,
        params=params,
        project_id=shot.project_id,
    )
    try:
        await start_pipeline_job(job, images={"layout": (filename, data)})
    except Exception as exc:
        logger.exception("start_pipeline_job wan_i2v failed for %s", shot.id)
        raise H3SubmitError(f"Failed to start Wan job: {exc}", status_code=503) from exc

    shot = shot.model_copy(
        update={"status": ShotStatus.queued, "blocked_reasons": [], "h3_job_id": job.id}
    )
    save_shot(shot)
    return load_shot(shot.project_id, shot.id) or shot
