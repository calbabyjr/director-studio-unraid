from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ...config import settings
from ...core.jobs import (
    cancel_job,
    create_job,
    enrich_job_urls,
    list_jobs,
    load_job,
    save_job,
    start_pipeline_job,
)
from ...core.library import list_assets, load_asset
from ...core.schemas import JobStatus
from ...pipelines.registry import get_pipeline
from ..prop.schemas import PropJobResponse, PropListResponse, PropRecord, SavePropRequest

router = APIRouter(tags=["costumes"])
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


async def _read_image(upload: UploadFile | None, field: str) -> tuple[str, bytes] | None:
    if upload is None:
        return None
    filename = upload.filename or f"{field}.png"
    ext = Path(filename).suffix.lower()
    if ext and ext not in ALLOWED_EXT:
        raise HTTPException(400, f"{field}: unsupported file type {ext}")
    data = await upload.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(400, f"{field}: file exceeds {settings.max_upload_mb}MB")
    if len(data) == 0:
        raise HTTPException(400, f"{field}: empty file")
    return filename, data


def _to_response(job) -> PropJobResponse:
    pipe = get_pipeline("costume")
    job = enrich_job_urls(job, labels=pipe.output_labels)
    return PropJobResponse.from_job(job, labels=pipe.output_labels)


@router.get("/meta/costume-defaults")
async def costume_defaults() -> dict:
    meta = get_pipeline("costume").meta_defaults()
    meta["max_upload_mb"] = settings.max_upload_mb
    return meta


@router.post("/costumes/generate", response_model=PropJobResponse)
async def generate_costume(
    name: str = Form(...),
    notes: str = Form(""),
    seed: str = Form(""),
    fixed_seed: bool = Form(False),
    project_id: str = Form(""),
    costume_image: UploadFile | None = File(None),
) -> PropJobResponse:
    name = (name or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    image = await _read_image(costume_image, "costume_image")
    if not image:
        raise HTTPException(400, "costume_image is required")
    seed_val = None
    if seed.strip():
        try:
            seed_val = int(seed.strip())
        except ValueError as exc:
            raise HTTPException(400, "seed must be an integer") from exc
    pipe = get_pipeline("costume")
    proj = (project_id or "").strip() or None
    job = create_job(
        pipeline_id=pipe.id,
        asset_kind=pipe.asset_kind,
        name=name,
        notes=notes,
        params={},
        seed=seed_val,
        fixed_seed=fixed_seed,
        project_id=proj,
    )
    job = await start_pipeline_job(job, images={"costume": image})
    return _to_response(job)


@router.get("/costumes/jobs/{job_id}", response_model=PropJobResponse)
async def get_job(job_id: str) -> PropJobResponse:
    job = load_job(job_id)
    if not job or job.pipeline_id != "costume":
        raise HTTPException(404, "Job not found")
    return _to_response(job)


@router.get("/costumes/jobs", response_model=list[PropJobResponse])
async def list_costume_jobs(limit: int = 30, project_id: str | None = None) -> list[PropJobResponse]:
    return [
        _to_response(job)
        for job in list_jobs(limit, pipeline_id="costume", project_id=project_id or None)
    ]


@router.post("/costumes/jobs/{job_id}/cancel", response_model=PropJobResponse)
async def cancel_costume_job(job_id: str) -> PropJobResponse:
    job = load_job(job_id)
    if not job or job.pipeline_id != "costume":
        raise HTTPException(404, "Job not found")
    job = await cancel_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _to_response(job)


@router.post("/costumes/jobs/{job_id}/save", response_model=PropRecord)
async def save_job_to_library(job_id: str, body: SavePropRequest | None = None) -> PropRecord:
    job = load_job(job_id)
    if not job or job.pipeline_id != "costume":
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.succeeded:
        raise HTTPException(400, f"Job status is {job.status}, need succeeded")
    pipe = get_pipeline("costume")
    proj = (body.project_id if body else None) or job.project_id
    if isinstance(proj, str):
        proj = proj.strip() or None
    try:
        if proj and not job.project_id:
            job.project_id = proj
            save_job(job)
        asset = pipe.save_to_library(
            job,
            name=body.name if body else None,
            notes=body.notes if body else None,
            project_id=proj,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return PropRecord.from_library(asset)


@router.get("/costumes", response_model=PropListResponse)
async def list_costumes(project_id: str | None = None, include_unassigned: bool = False) -> PropListResponse:
    return PropListResponse(
        items=[
            PropRecord.from_library(asset)
            for asset in list_assets(
                "costumes",
                project_id=project_id or None,
                include_unassigned=include_unassigned,
            )
        ]
    )
