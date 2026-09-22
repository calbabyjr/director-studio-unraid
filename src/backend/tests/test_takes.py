from __future__ import annotations

import pytest

from app.core.jobs.store import create_job, job_dir, save_job
from app.core.library.store import create_external_asset
from app.core.projects.models import Shot, ShotStatus
from app.core.projects.store import create_project, save_shot
from app.core.projects.takes import pin_actor_take, pin_h3_take
from app.core.schemas import JobStatus, OutputSlot


def test_pin_h3_take_sets_canonical_job():
    project = create_project("Takes", "Jenny waits.")
    shot = Shot(
        id="sht_pin",
        project_id=project.id,
        scene_id="sc1",
        title="Hold",
        script_beat="Jenny waits.",
        duration_s=4,
        status=ShotStatus.failed,
        h3_job_id="job_old",
    )
    save_shot(shot)
    job = create_job(
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        name="h3:Hold",
        params={"shot_id": shot.id, "project_id": project.id},
        project_id=project.id,
    )
    job = job.model_copy(update={"status": JobStatus.succeeded})
    save_job(job)

    updated = pin_h3_take(project.id, shot.id, job.id)
    assert updated.h3_job_id == job.id
    assert updated.status == ShotStatus.succeeded


def test_pin_h3_take_becomes_sequence_clip():
    from app.core.media.sequence import SequenceClipStatus, resolve_shot_clip
    from app.core.projects.store import load_shot

    project = create_project("Takes pin clip", "Jenny waits.")
    shot = Shot(
        id="sht_pin_clip",
        project_id=project.id,
        scene_id="sc1",
        title="Hold",
        script_beat="Jenny waits.",
        duration_s=4,
        status=ShotStatus.succeeded,
    )
    save_shot(shot)

    def _take(name: str, created_at: str) -> str:
        job = create_job(
            pipeline_id="h3_ref2va",
            asset_kind="productions",
            name=name,
            params={"shot_id": shot.id, "project_id": project.id},
            project_id=project.id,
        )
        out = job_dir(job.id, project_id=project.id) / "outputs"
        out.mkdir(parents=True, exist_ok=True)
        path = out / "video.mp4"
        path.write_bytes(b"fake-mp4")
        job = job.model_copy(
            update={
                "status": JobStatus.succeeded,
                "created_at": created_at,
                "outputs": {
                    "video": OutputSlot(
                        key="video",
                        label="Video",
                        path=str(path),
                        filename="video.mp4",
                    )
                },
            }
        )
        save_job(job)
        return job.id

    older = _take("h3:Hold v1", "2026-08-01T10:00:00+00:00")
    newer = _take("h3:Hold v2", "2026-08-01T11:00:00+00:00")
    save_shot(shot.model_copy(update={"h3_job_id": newer}))

    clip, status = resolve_shot_clip(project.id, load_shot(project.id, shot.id))
    assert clip is not None
    assert clip.source_job_id == newer
    assert status == SequenceClipStatus.ready

    updated = pin_h3_take(project.id, shot.id, older)
    assert updated.h3_job_id == older
    clip, status = resolve_shot_clip(project.id, updated)
    assert clip is not None
    assert clip.source_job_id == older
    assert status == SequenceClipStatus.ready


def test_pin_h3_take_rejects_non_succeeded():
    project = create_project("Takes fail", "Jenny waits.")
    shot = Shot(
        id="sht_pin_fail",
        project_id=project.id,
        scene_id="sc1",
        title="Hold",
        script_beat="Jenny waits.",
        duration_s=4,
    )
    save_shot(shot)
    job = create_job(
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        name="h3:Hold",
        params={"shot_id": shot.id, "project_id": project.id},
        project_id=project.id,
    )
    with pytest.raises(ValueError, match="succeeded take"):
        pin_h3_take(project.id, shot.id, job.id)


def test_pin_actor_take_copies_outputs():
    actor = create_external_asset(
        kind="actors",
        name="Jenny",
        image_bytes=b"\x89PNG\r\n" + b"x" * 80,
        image_filename="master.png",
        project_id="prj_pin_actor",
    )
    job = create_job(
        pipeline_id="actor",
        asset_kind="actors",
        name="Jenny",
        params={"actor_id": actor.id},
        project_id=actor.project_id,
    )
    out = job_dir(job.id, project_id=job.project_id) / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "master.png").write_bytes(b"\x89PNG\r\n" + b"take" * 20)
    job = job.model_copy(
        update={
            "status": JobStatus.succeeded,
            "library_asset_id": actor.id,
            "outputs": {
                "master": OutputSlot(
                    key="master",
                    label="master",
                    filename="master.png",
                )
            },
        }
    )
    save_job(job)

    updated = pin_actor_take(actor.id, job.id)
    assert updated.job_id == job.id
    assert updated.meta["pinned_take_job_id"] == job.id
    assert updated.files["master"] == "master.png"
    from app.core.paths import asset_write_dir

    dest = asset_write_dir("actors", actor.id, project_id=actor.project_id) / "master.png"
    assert dest.is_file()
    assert dest.read_bytes().endswith(b"take" * 20)
