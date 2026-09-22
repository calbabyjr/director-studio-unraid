"""Storyboard sequence rundown, rough-cut assembly, and editorial exports."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..agents.director import DirectorService
from ..core.media.sequence import (
    SequenceError,
    assemble_rough_cut,
    build_sequence_report,
    render_edl,
    render_shot_list_csv,
    render_srt,
)
from ..core.projects.shot_queue import (
    cancel_production_queue,
    load_queue,
    start_production_queue,
)
from ..core.projects.store import load_project
from ..core.projects.takes import list_h3_takes, pin_h3_take
from .projects import get_director_service

router = APIRouter(tags=["sequence"])

_EXPORT_KINDS = frozenset({"srt", "edl", "csv"})


class ProductionQueueBody(BaseModel):
    mode: str = Field("next", description="next or remaining")
    from_shot_id: str | None = None
    chain_tail_frames: bool = True


def _require_project(project_id: str) -> None:
    if load_project(project_id) is None:
        raise HTTPException(404, "Project not found")


@router.get("/projects/{project_id}/sequence")
def get_sequence(project_id: str) -> dict:
    _require_project(project_id)
    try:
        return build_sequence_report(project_id).model_dump(mode="json")
    except SequenceError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/projects/{project_id}/sequence/assemble")
def post_sequence_assemble(project_id: str) -> dict:
    _require_project(project_id)
    try:
        assembly = assemble_rough_cut(project_id)
    except SequenceError as exc:
        raise HTTPException(400, str(exc)) from exc
    return assembly.model_dump(mode="json")


@router.get("/projects/{project_id}/sequence/export/{kind}")
def get_sequence_export(project_id: str, kind: str) -> PlainTextResponse:
    _require_project(project_id)
    export_kind = kind.strip().lower()
    if export_kind not in _EXPORT_KINDS:
        raise HTTPException(404, "Unknown export; use srt, edl, or csv")
    try:
        report = build_sequence_report(project_id)
    except SequenceError as exc:
        raise HTTPException(400, str(exc)) from exc

    if export_kind == "srt":
        body = render_srt(report)
        filename = "dialogue.srt"
        media_type = "application/x-subrip"
    elif export_kind == "edl":
        body = render_edl(report)
        filename = "sequence.edl"
        media_type = "text/plain"
    else:
        body = render_shot_list_csv(report)
        filename = "shot-list.csv"
        media_type = "text/csv"

    return PlainTextResponse(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{project_id}/production/queue")
def get_production_queue(project_id: str) -> dict:
    _require_project(project_id)
    return load_queue(project_id).model_dump(mode="json")


@router.post("/projects/{project_id}/production/queue")
async def post_production_queue(
    project_id: str,
    body: ProductionQueueBody,
    svc: DirectorService = Depends(get_director_service),
) -> dict:
    _require_project(project_id)
    mode = (body.mode or "next").strip().lower()
    if mode not in {"next", "remaining"}:
        raise HTTPException(400, "mode must be next or remaining")
    try:
        queue = await start_production_queue(
            project_id,
            mode=mode,  # type: ignore[arg-type]
            from_shot_id=body.from_shot_id,
            chain_tail_frames=body.chain_tail_frames,
            director_service=svc,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return queue.model_dump(mode="json")


@router.post("/projects/{project_id}/production/queue/cancel")
async def post_production_queue_cancel(project_id: str) -> dict:
    _require_project(project_id)
    queue = await cancel_production_queue(project_id)
    return queue.model_dump(mode="json")


@router.get("/projects/{project_id}/shots/{shot_id}/takes")
def get_shot_takes(project_id: str, shot_id: str) -> dict:
    _require_project(project_id)
    from ..core.projects.store import load_shot

    takes = list_h3_takes(project_id, shot_id)
    shot = load_shot(project_id, shot_id)
    pinned = shot.h3_job_id if shot else None
    return {
        "items": [
            {
                "id": job.id,
                "status": job.status.value,
                "created_at": job.created_at,
                "error": job.error,
                "pinned": pinned == job.id,
            }
            for job in takes
        ]
    }


@router.post("/projects/{project_id}/shots/{shot_id}/takes/{job_id}/pin")
def post_pin_shot_take(project_id: str, shot_id: str, job_id: str) -> dict:
    _require_project(project_id)
    try:
        shot = pin_h3_take(project_id, shot_id, job_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return shot.model_dump(mode="json")
