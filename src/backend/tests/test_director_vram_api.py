from __future__ import annotations

import pytest

from app.api import director as director_api
from app.core.vram import GenerationReservation


class FakeOllama:
    async def loaded_models(self):
        return []

    async def model_vram_bytes(self, model: str) -> int:
        return 0


class FakeOrchestrator:
    owner = None
    comfy_pipeline = None
    policy = "exclusive"
    models = ["qwen-test"]
    acquire_timeout_sec = 3600
    _llm_ready = False
    _waiters = 0
    last_comfy_free = None
    last_comfy_free_error = None
    ollama = FakeOllama()

    async def generation_reservations(self):
        return [
            GenerationReservation(
                job_id="job_video",
                pipeline_id="h3_ref2va",
                kind="video",
                status="running",
                phase="generating",
                queued_at="2026-08-31T10:00:00+00:00",
            )
        ]


@pytest.mark.asyncio
async def test_vram_status_exposes_generation_chat_lock(monkeypatch):
    monkeypatch.setattr(director_api, "get_orchestrator", FakeOrchestrator)
    monkeypatch.setattr(director_api, "get_director_model", lambda: "qwen-test")

    async def fake_queue():
        return {"running": 1, "pending": 2, "prompt_id": "prompt-abc"}

    monkeypatch.setattr(director_api, "_comfy_queue_snapshot", fake_queue)

    result = await director_api.vram_status()

    assert result["chat_locked"] is True
    assert result["director_working"] is False
    assert result["director_chats"] == []
    assert result["generation_count"] == 1
    assert result["cancel_job_id"] == "job_video"
    assert result["comfy_queue"] == {
        "running": 1,
        "pending": 2,
        "prompt_id": "prompt-abc",
    }
    assert result["generation_jobs"] == [
        {
            "job_id": "job_video",
            "pipeline_id": "h3_ref2va",
            "kind": "video",
            "status": "running",
            "phase": "generating",
            "queued_at": "2026-08-31T10:00:00+00:00",
        }
    ]


@pytest.mark.asyncio
async def test_cancel_director_job(monkeypatch):
    from app.core.schemas import JobRecord, JobStatus

    job = JobRecord(
        id="job_video",
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        status=JobStatus.running,
        name="h3",
        created_at="t",
        updated_at="t",
    )

    monkeypatch.setattr("app.core.jobs.load_job", lambda _job_id: job)

    async def fake_cancel(_job_id):
        return job.model_copy(update={"status": JobStatus.cancelled})

    monkeypatch.setattr("app.core.jobs.cancel_job", fake_cancel)
    result = await director_api.cancel_director_job("job_video")
    assert result == {"ok": True, "id": "job_video", "status": "cancelled"}


@pytest.mark.asyncio
async def test_cancel_director_job_missing(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr("app.core.jobs.load_job", lambda _job_id: None)
    with pytest.raises(HTTPException) as exc:
        await director_api.cancel_director_job("job_missing")
    assert exc.value.status_code == 404
