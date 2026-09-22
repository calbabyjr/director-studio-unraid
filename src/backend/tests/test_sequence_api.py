"""HTTP API for sequence rundown, assembly, and exports."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.jobs.store import create_job, job_dir, save_job
from app.core.projects.layouts import RefRole
from app.core.projects.models import PromptSections, Shot, ShotRef, ShotStatus, ShotVoiceRef
from app.core.projects.store import create_project, save_project, save_shot
from app.core.schemas import JobStatus, OutputSlot


@pytest.fixture
def client(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    jobs = tmp_path / "jobs"
    library = tmp_path / "library"
    projects.mkdir()
    jobs.mkdir()
    library.mkdir()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", projects)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "library_root", library)

    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def _prompt() -> PromptSections:
    return PromptSections(
        subject_definitions="subject",
        summary="summary",
        retention_analysis="retention",
        detailed_description="detailed",
        overall_soundscape="sound",
        non_diegetic_music="music",
    )


def _seed(client: TestClient, *, with_clip: bool = False) -> str:
    project = create_project("Cut", "INT. HALL")
    shot = Shot(
        id="sht_entry",
        project_id=project.id,
        scene_id="sc01",
        title="Entry",
        script_beat="Kai enters.",
        duration_s=6,
        status=ShotStatus.succeeded if with_clip else ShotStatus.draft,
        prompt_sections=_prompt(),
        dialogue=["Kai: Hello."],
        voice_refs=[ShotVoiceRef(asset_id="voice_kai", audio_index=1, speaker="Kai")],
        refs=[ShotRef(role=RefRole.actor, asset_id="act_kai", picture_index=1)],
    )
    save_shot(shot)
    save_project(project.model_copy(update={"shot_ids": [shot.id]}))
    if with_clip:
        job = create_job(
            pipeline_id="h3_ref2va",
            asset_kind="productions",
            name="entry v1",
            project_id=project.id,
            params={"shot_id": shot.id, "project_id": project.id},
        )
        out_dir = job_dir(job.id, project_id=project.id) / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "video.mp4"
        path.write_bytes(b"fake-mp4")
        job.status = JobStatus.succeeded
        job.outputs = {
            "video": OutputSlot(
                key="video",
                label="Video",
                path=str(path),
                filename="video.mp4",
                url=f"/api/files/jobs/{job.id}/outputs/video.mp4",
            )
        }
        save_job(job)
    return project.id


def test_sequence_report_and_exports(client):
    project_id = _seed(client)
    response = client.get(f"/api/projects/{project_id}/sequence")
    assert response.status_code == 200
    payload = response.json()
    assert payload["shot_count"] == 1
    assert payload["clips_ready"] == 0
    assert payload["runtime"] == "0:06"
    assert payload["shots"][0]["title"] == "Entry"

    srt = client.get(f"/api/projects/{project_id}/sequence/export/srt")
    assert srt.status_code == 200
    assert "Kai: Hello." in srt.text
    assert 'filename="dialogue.srt"' in srt.headers["content-disposition"]

    edl = client.get(f"/api/projects/{project_id}/sequence/export/edl")
    assert edl.status_code == 200
    assert "SHOT: 01 Entry" in edl.text

    csv = client.get(f"/api/projects/{project_id}/sequence/export/csv")
    assert csv.status_code == 200
    assert "sht_entry" in csv.text

    missing = client.get(f"/api/projects/{project_id}/sequence/export/txt")
    assert missing.status_code == 404


def test_assemble_without_clips_is_400(client):
    project_id = _seed(client)
    response = client.post(f"/api/projects/{project_id}/sequence/assemble")
    assert response.status_code == 400
    assert "no succeeded clips" in response.json()["detail"]


def test_unknown_project_is_404(client):
    response = client.get("/api/projects/prj_missing/sequence")
    assert response.status_code == 404


def test_production_queue_cancel_cancels_inflight_job(client, monkeypatch):
    from app.core.projects.shot_queue import ProductionQueue, save_queue

    project_id = _seed(client)
    save_queue(
        ProductionQueue(
            project_id=project_id,
            mode="remaining",
            status="running",
            current_shot_id="sht_entry",
            current_job_id="job_h3_run",
            pending_shot_ids=["sht_entry"],
        )
    )
    cancelled: list[str] = []

    async def fake_cancel(job_id: str):
        cancelled.append(job_id)
        return None

    monkeypatch.setattr("app.core.jobs.cancel_job", fake_cancel)
    response = client.post(f"/api/projects/{project_id}/production/queue/cancel")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "idle"
    assert body["current_job_id"] is None
    assert cancelled == ["job_h3_run"]
