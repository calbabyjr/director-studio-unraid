"""Storyboard sequence rundown, rough-cut assembly, and editorial exports."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from ..core.media.sequence import (
    SequenceError,
    assemble_rough_cut,
    build_sequence_report,
    render_edl,
    render_shot_list_csv,
    render_srt,
)
from ..core.projects.store import load_project

router = APIRouter(tags=["sequence"])

_EXPORT_KINDS = frozenset({"srt", "edl", "csv"})


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
