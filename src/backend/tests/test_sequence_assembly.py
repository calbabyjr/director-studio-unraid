"""ffmpeg rough-cut assembly for succeeded H3 clips."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import settings
from app.core.jobs.store import create_job, job_dir, save_job
from app.core.media.sequence import SequenceError, assemble_rough_cut, build_sequence_report
from app.core.projects.layouts import RefRole
from app.core.projects.models import PromptSections, Shot, ShotRef, ShotStatus
from app.core.projects.store import create_project, project_dir, save_project, save_shot
from app.core.schemas import JobStatus, OutputSlot


def _ffmpeg() -> str:
    resolved = shutil.which("ffmpeg")
    if not resolved:
        pytest.fail("ffmpeg is required for sequence assembly tests")
    return resolved


def _write_color_clip(path: Path, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            _ffmpeg(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=32x32:d=0.5:r=8",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _prompt() -> PromptSections:
    return PromptSections(
        subject_definitions="subject",
        summary="summary",
        retention_analysis="retention",
        detailed_description="detailed",
        overall_soundscape="sound",
        non_diegetic_music="music",
    )


def test_assemble_concatenates_ready_clips_and_skips_missing(
    tmp_projects_dir, monkeypatch
):
    jobs = tmp_projects_dir.parent / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "data_dir", tmp_projects_dir.parent)

    project = create_project("Cut", "INT. HALL")
    first = Shot(
        id="sht_a",
        project_id=project.id,
        scene_id="sc01",
        title="Red",
        script_beat="Red",
        duration_s=1,
        status=ShotStatus.succeeded,
        prompt_sections=_prompt(),
        refs=[ShotRef(role=RefRole.actor, asset_id="act_kai", picture_index=1)],
        dialogue=["Kai: Go."],
    )
    second = Shot(
        id="sht_b",
        project_id=project.id,
        scene_id="sc01",
        title="Missing",
        script_beat="Missing",
        duration_s=1,
        status=ShotStatus.draft,
        prompt_sections=_prompt(),
    )
    third = Shot(
        id="sht_c",
        project_id=project.id,
        scene_id="sc01",
        title="Blue",
        script_beat="Blue",
        duration_s=1,
        status=ShotStatus.succeeded,
        prompt_sections=_prompt(),
        refs=[ShotRef(role=RefRole.actor, asset_id="act_kai", picture_index=1)],
    )
    save_shot(first)
    save_shot(second)
    save_shot(third)
    save_project(project.model_copy(update={"shot_ids": [first.id, second.id, third.id]}))

    for shot_id, color in ((first.id, "red"), (third.id, "blue")):
        job = create_job(
            pipeline_id="h3_ref2va",
            asset_kind="productions",
            name=shot_id,
            project_id=project.id,
            params={"shot_id": shot_id, "project_id": project.id},
        )
        out_dir = job_dir(job.id, project_id=project.id) / "outputs"
        path = out_dir / "video.mp4"
        _write_color_clip(path, color)
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

    assembly = assemble_rough_cut(project.id)
    assert assembly.shot_ids == [first.id, third.id]
    assert assembly.missing_shot_ids == [second.id]
    video = project_dir(project.id) / "sequence" / "rough_cut.mp4"
    assert video.is_file()
    assert video.stat().st_size > 0
    srt = (project_dir(project.id) / "sequence" / "rough_cut.srt").read_text(
        encoding="utf-8"
    )
    assert "Kai: Go." in srt

    report = build_sequence_report(project.id)
    assert report.last_assembly is not None
    assert report.last_assembly.url.endswith("/sequence/rough_cut.mp4")


def test_assemble_uses_pinned_take_not_latest(tmp_projects_dir, monkeypatch):
    jobs = tmp_projects_dir.parent / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "data_dir", tmp_projects_dir.parent)

    project = create_project("Cut", "INT. HALL")
    shot = Shot(
        id="sht_a",
        project_id=project.id,
        scene_id="sc01",
        title="Hold",
        script_beat="Hold",
        duration_s=1,
        status=ShotStatus.succeeded,
        prompt_sections=_prompt(),
        refs=[ShotRef(role=RefRole.actor, asset_id="act_kai", picture_index=1)],
    )
    save_shot(shot)
    save_project(project.model_copy(update={"shot_ids": [shot.id]}))

    job_ids: list[str] = []
    for created_at, color in (
        ("2026-08-01T10:00:00+00:00", "red"),
        ("2026-08-01T11:00:00+00:00", "blue"),
    ):
        job = create_job(
            pipeline_id="h3_ref2va",
            asset_kind="productions",
            name=f"{shot.id}-{color}",
            project_id=project.id,
            params={"shot_id": shot.id, "project_id": project.id},
        )
        out_dir = job_dir(job.id, project_id=project.id) / "outputs"
        path = out_dir / "video.mp4"
        _write_color_clip(path, color)
        job.created_at = created_at
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
        job_ids.append(job.id)

    older, newer = job_ids
    save_shot(shot.model_copy(update={"h3_job_id": older, "status": ShotStatus.succeeded}))

    assembly = assemble_rough_cut(project.id)
    assert assembly.shot_ids == [shot.id]
    assert assembly.clip_job_ids == [older]
    assert newer not in assembly.clip_job_ids

    report = build_sequence_report(project.id)
    assert report.shots[0].clip_job_id == older


def test_assemble_without_ffmpeg_explains_the_requirement(
    tmp_projects_dir, monkeypatch
):
    jobs = tmp_projects_dir.parent / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "data_dir", tmp_projects_dir.parent)
    monkeypatch.setattr("app.core.media.sequence.shutil.which", lambda name: None)

    project = create_project("Cut", "INT. HALL")
    shot = Shot(
        id="sht_a",
        project_id=project.id,
        scene_id="sc01",
        title="Red",
        script_beat="Red",
        duration_s=1,
        status=ShotStatus.succeeded,
        prompt_sections=_prompt(),
        refs=[ShotRef(role=RefRole.actor, asset_id="act_kai", picture_index=1)],
    )
    save_shot(shot)
    save_project(project.model_copy(update={"shot_ids": [shot.id]}))
    job = create_job(
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        name="a",
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
            url="/video.mp4",
        )
    }
    save_job(job)

    with pytest.raises(SequenceError, match="ffmpeg is required"):
        assemble_rough_cut(project.id)
