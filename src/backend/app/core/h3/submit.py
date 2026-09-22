"""Shared H3 Ref2AV submit used by the HTTP endpoint and production queue."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel

from ...config import settings
from ..jobs.store import create_job, load_job
from ..library.store import asset_dir, load_asset
from ..projects.layouts import (
    layout_prompt_signature,
    selected_layout_prompt_context,
    sync_selected_layout_refs,
)
from ..projects.models import (
    PromptSections,
    Shot,
    ShotStatus,
    ShotVoiceRef,
    picture_ref_signature,
    voice_ref_signature,
)
from ..projects.store import load_project, load_shot, save_shot
from ..projects.transitions import apply_transition, assert_h3_submittable
from ..schemas import JobRecord, JobStatus, LibraryAsset
from .images import collect_h3_images
from .frames import frames_for_audio_seconds, frames_for_seconds
from .prompt import (
    compose_h3_prompt,
    merge_user_locked_prompt,
    user_locked_prompt_dict,
    validate_h3_prompt,
)

logger = logging.getLogger("director_studio.h3.submit")

StartJob = Callable[..., Awaitable[JobRecord]]


class H3SubmitOptions(BaseModel):
    h3_provider: Literal["local", "minimax"] | None = None
    width: int | None = None
    height: int | None = None


class H3SubmitError(Exception):
    """Submit failure with an HTTP-shaped status for the API layer."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        detail: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = message if detail is None else detail


def validate_voice_refs(shot: Shot) -> list[tuple[ShotVoiceRef, LibraryAsset, Path]]:
    resolved: list[tuple[ShotVoiceRef, LibraryAsset, Path]] = []
    total_duration = 0.0
    for ref in shot.voice_refs:
        asset = load_asset("voices", ref.asset_id)
        if asset is None:
            raise ValueError(f"Voice asset not found: {ref.asset_id}")
        if asset.kind != "voices":
            raise ValueError(f"asset is not a Voice reference: {ref.asset_id}")
        if asset.project_id != shot.project_id:
            raise ValueError(f"Voice asset belongs to another project: {ref.asset_id}")
        if not bool((asset.meta or {}).get("h3_ready")):
            raise ValueError(f"Voice asset is not H3-ready: {ref.asset_id}")
        filename = (asset.files or {}).get(ref.file_key)
        if not filename:
            raise ValueError(
                f"Voice asset missing file key {ref.file_key!r}: {ref.asset_id}"
            )
        path = asset_dir("voices", ref.asset_id, project_id=asset.project_id) / filename
        if not path.is_file():
            raise ValueError(f"Voice reference file not found: {ref.asset_id}/{filename}")
        try:
            duration = float((asset.meta or {}).get("duration_s"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Voice asset duration is invalid: {ref.asset_id}") from exc
        total_duration += duration
        resolved.append((ref, asset, path))
    if total_duration > 15.0:
        raise ValueError("Voice reference total duration must not exceed 15 seconds")
    return resolved


def stage_voice_audio(shot: Shot) -> dict[str, tuple[str, bytes]]:
    """Stage H3-ready Voice files in audio_index order."""
    if shot.source_audio_path:
        raise ValueError(
            "The official H3 Ref2AV workflow cannot preserve locked source audio "
            "exactly; remove the source track or submit it as reference audio."
        )
    audio: dict[str, tuple[str, bytes]] = {}
    for ref, _asset, audio_path in validate_voice_refs(shot):
        audio[f"voice_audio_{ref.audio_index}"] = (
            audio_path.name,
            audio_path.read_bytes(),
        )
    return audio


def graft_locked_prompt_bindings(shot: Shot) -> PromptSections:
    """Keep Production-tab wording and graft missing Picture/Audio tags."""
    locked = user_locked_prompt_dict(shot)
    current = shot.prompt_sections or PromptSections()
    pic_tags = " ".join(f"<Picture {ref.picture_index}>" for ref in shot.refs)
    audio_tags = ""
    if not shot.source_audio_path:
        audio_tags = " ".join(
            f"<Audio {ref.audio_index}>" for ref in shot.voice_refs
        )
    stub_subject = " ".join(
        part for part in (current.subject_definitions, pic_tags, audio_tags) if part
    ).strip()
    generated = current.model_copy(update={"subject_definitions": stub_subject})
    return merge_user_locked_prompt(generated, locked)


def _portrait_script(shot: Shot) -> bool:
    project = load_project(shot.project_id)
    return bool(
        project
        and any(
            marker in project.script_text.lower()
            for marker in ("9:16", "9／16", "竖屏", "vertical")
        )
    )


def _signatures_stale(shot: Shot, selected_layouts: list[dict[str, Any]]) -> bool:
    current_layout_signature = layout_prompt_signature(shot)
    prompt_layout_signature = str(
        (shot.meta or {}).get("prompt_layout_signature") or ""
    )
    layout_contract_present = (
        bool(shot.layout_refs)
        or bool(selected_layouts)
        or any(
            key in (shot.meta or {})
            for key in (
                "prompt_layout_asset_id",
                "prompt_layout_asset_ids",
                "prompt_layout_signature",
            )
        )
    )
    prompt_voice_signature = str(
        (shot.meta or {}).get("prompt_voice_signature") or ""
    )
    prompt_picture_signature = str(
        (shot.meta or {}).get("prompt_picture_signature") or ""
    )
    current_picture_signature = picture_ref_signature(shot.refs)
    picture_contract_present = "prompt_picture_signature" in (shot.meta or {})
    current_voice_signature = voice_ref_signature(shot.voice_refs)
    voice_contract_present = bool(shot.voice_refs) or (
        "prompt_voice_signature" in (shot.meta or {})
    )
    return (
        (picture_contract_present and prompt_picture_signature != current_picture_signature)
        or (
            layout_contract_present
            and prompt_layout_signature != current_layout_signature
        )
        or (
            not shot.source_audio_path
            and voice_contract_present
            and prompt_voice_signature != current_voice_signature
        )
    )


async def _start_pipeline_job(
    job: JobRecord,
    *,
    images: dict[str, tuple[str, bytes]] | None,
    start_job: StartJob | None,
) -> JobRecord:
    starter = start_job
    if starter is None:
        from ..jobs.runner import start_pipeline_job

        starter = start_pipeline_job
    return await starter(job, images=images)


async def _write_prompts_after_layout(shot: Shot, director_service: Any | None) -> Shot:
    svc = director_service
    if svc is None:
        from ...agents.director import DirectorService
        from ...agents.director.llm_plan_provider import DirectorLLMPlanProvider

        svc = DirectorService(plan_provider=DirectorLLMPlanProvider())
    return await svc.write_prompts_after_layout(shot.id)


async def submit_h3_shot(
    shot: Shot,
    *,
    options: H3SubmitOptions | None = None,
    director_service: Any | None = None,
    queued_by: str | None = None,
    skip_prompt_refresh: bool = False,
    start_job: StartJob | None = None,
) -> Shot:
    """Queue pure H3 Ref2AV after preflight, matching POST /api/shots/{id}/submit."""
    h3_provider = str(
        (
            options.h3_provider
            if options and options.h3_provider
            else settings.h3_provider
        )
        or "local"
    ).strip().lower()
    if h3_provider not in {"local", "minimax"}:
        raise ValueError(f"Unsupported H3 provider: {h3_provider}")
    if h3_provider == "minimax" and not str(
        settings.h3_minimax_api_key or ""
    ).strip():
        raise ValueError("MiniMax H3 API key is not configured")

    if shot.status in (ShotStatus.queued, ShotStatus.running):
        raise H3SubmitError(
            f"shot already {shot.status.value}",
            status_code=409,
        )
    if shot.h3_job_id:
        existing = load_job(shot.h3_job_id)
        if existing and existing.status in (
            JobStatus.queued,
            JobStatus.uploading,
            JobStatus.running,
        ):
            raise H3SubmitError(
                f"H3 job already active: {shot.h3_job_id} ({existing.status.value})",
                status_code=409,
            )

    synchronized = sync_selected_layout_refs(shot)
    selected_layouts = selected_layout_prompt_context(synchronized)
    if synchronized.refs != shot.refs:
        shot = synchronized
        save_shot(shot)
    else:
        shot = synchronized

    if bool((shot.meta or {}).get("material_review_pending")):
        # skip_prompt_refresh must never bypass this gate.
        raise H3SubmitError(
            (
                "Shot references changed. Ask the Director to review the current "
                "materials and refresh the H3 prompt before submitting."
            ),
            status_code=409,
            detail={
                "code": "material_review_required",
                "shot_id": shot.id,
                "message": (
                    "Shot references changed. Ask the Director to review the current "
                    "materials and refresh the H3 prompt before submitting."
                ),
                "changes": (shot.meta or {}).get("material_changes") or {},
            },
        )

    locked = user_locked_prompt_dict(shot)
    if locked:
        grafted = graft_locked_prompt_bindings(shot)
        if grafted != shot.prompt_sections:
            shot = shot.model_copy(update={"prompt_sections": grafted})
            save_shot(shot)

    if (
        not skip_prompt_refresh
        and not locked
        and _signatures_stale(shot, selected_layouts)
    ):
        try:
            shot = await _write_prompts_after_layout(shot, director_service)
        except ValueError:
            raise
        except Exception as exc:
            logger.exception(
                "write_prompts_after_layout before H3 submit failed for %s",
                shot.id,
            )
            raise H3SubmitError(
                f"Prompt refresh for current layout failed: {exc}",
                status_code=503,
            ) from exc
        selected_layouts = selected_layout_prompt_context(shot)

    assert_h3_submittable(shot)

    prompt_text = compose_h3_prompt(shot.prompt_sections)
    required_layout_indices = [
        int(item["picture_index"]) for item in selected_layouts
    ]
    validate_h3_prompt(
        prompt_text,
        list(shot.dialogue),
        audio_count=0 if shot.source_audio_path else len(shot.voice_refs),
        required_picture_indices=required_layout_indices,
        submitted_picture_indices=(ref.picture_index for ref in shot.refs),
    )

    frames = (
        frames_for_audio_seconds(shot.duration_s)
        if shot.source_audio_path
        else frames_for_seconds(shot.duration_s)
    )
    images = collect_h3_images(shot)
    image_keys = list(images.keys())
    audio_keys: list[str] = []
    if not shot.source_audio_path:
        voice_audio = stage_voice_audio(shot)
        audio_keys = list(voice_audio.keys())
        images.update(voice_audio)

    if shot.source_audio_path:
        raise ValueError(
            "The official H3 Ref2AV workflow cannot preserve locked source audio "
            "exactly; remove the source track or submit it as reference audio."
        )

    portrait = _portrait_script(shot)
    width = (
        int(options.width)
        if options is not None and options.width is not None
        else (480 if portrait else 864)
    )
    height = (
        int(options.height)
        if options is not None and options.height is not None
        else (864 if portrait else 480)
    )

    params: dict[str, Any] = {
        "h3_provider": h3_provider,
        "prompt": prompt_text,
        "dialogue": list(shot.dialogue),
        "frames": frames,
        "duration_s": shot.duration_s,
        "image_keys": image_keys,
        "audio_keys": audio_keys,
        "native_audio_key": None,
        "width": width,
        "height": height,
        "shot_id": shot.id,
        "project_id": shot.project_id,
        "layout_asset_id": shot.layout_asset_id,
        "layout_asset_ids": [str(item["asset_id"]) for item in selected_layouts],
        "layout_picture_indices": required_layout_indices,
        "ref_roles": [
            ref.role.value
            for ref in sorted(shot.refs or [], key=lambda item: item.picture_index)
        ][: len(image_keys)],
        "output_prefix": f"director-studio/{shot.project_id}/{shot.id}/h3",
        "prompt_locked": bool(locked),
    }
    if queued_by:
        params["queued_by"] = queued_by

    job = create_job(
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        name=f"h3:{shot.title}",
        notes=shot.script_beat,
        params=params,
        project_id=shot.project_id,
    )

    try:
        await _start_pipeline_job(job, images=images or None, start_job=start_job)
    except Exception as exc:
        logger.exception("start_pipeline_job h3_ref2va failed for %s", shot.id)
        raise H3SubmitError(
            f"Failed to start H3 job: {exc}",
            status_code=503,
        ) from exc

    shot = apply_transition(shot, "submit_h3")
    shot = shot.model_copy(update={"h3_job_id": job.id})
    save_shot(shot)
    return load_shot(shot.project_id, shot.id) or shot
