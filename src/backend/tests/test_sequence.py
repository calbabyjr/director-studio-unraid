"""Sequence rundown, continuity, and editorial export helpers."""

from __future__ import annotations

from app.config import settings
from app.core.jobs.store import create_job, job_dir, save_job
from app.core.media.sequence import (
    SequenceClipStatus,
    assemble_rough_cut,
    build_sequence_report,
    format_runtime,
    render_edl,
    render_shot_list_csv,
    render_srt,
    seconds_to_srt_timestamp,
    seconds_to_timecode,
)
from app.core.projects.layouts import ClipTailFrameOrigin, LayoutReference, RefRole
from app.core.projects.models import PromptSections, Shot, ShotRef, ShotStatus, ShotVoiceRef
from app.core.projects.store import create_project, save_project, save_shot
from app.core.schemas import JobStatus, OutputSlot


def _prompt(**overrides) -> PromptSections:
    base = dict(
        subject_definitions="subject",
        summary="summary",
        retention_analysis="retention",
        detailed_description="detailed",
        overall_soundscape="sound",
        non_diegetic_music="music",
    )
    base.update(overrides)
    return PromptSections(**base)


def _shot(project_id: str, shot_id: str, **updates) -> Shot:
    shot = Shot(
        id=shot_id,
        project_id=project_id,
        scene_id="sc01",
        title=shot_id,
        script_beat=shot_id,
        duration_s=6.0,
        status=ShotStatus.draft,
        prompt_sections=_prompt(),
        refs=[
            ShotRef(role=RefRole.actor, asset_id="act_kai", picture_index=1),
            ShotRef(role=RefRole.scene, asset_id="scn_hall", picture_index=2),
        ],
    )
    if updates:
        shot = shot.model_copy(update=updates)
    save_shot(shot)
    return shot


def _project_with_shots(*shots: Shot):
    project = create_project("Cut", "INT. HALL - DAY")
    for shot in shots:
        save_shot(shot.model_copy(update={"project_id": project.id}))
    save_project(
        project.model_copy(update={"shot_ids": [shot.id for shot in shots]})
    )
    return project


def _h3_clip(
    project_id: str,
    shot_id: str,
    *,
    filename: str = "video.mp4",
    created_at: str | None = None,
    status: JobStatus = JobStatus.succeeded,
    write_file: bool = True,
) -> str:
    job = create_job(
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        name=f"{shot_id} {filename}",
        project_id=project_id,
        params={"shot_id": shot_id, "project_id": project_id},
    )
    out_dir = job_dir(job.id, project_id=project_id) / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    if write_file:
        path.write_bytes(b"fake-mp4")
    if created_at is not None:
        job.created_at = created_at
    job.status = status
    if status == JobStatus.succeeded or write_file:
        job.outputs = {
            "video": OutputSlot(
                key="video",
                label="Video",
                path=str(path),
                filename=filename,
                url=f"/api/files/jobs/{job.id}/outputs/{filename}",
            )
        }
    save_job(job)
    return job.id


def test_runtime_and_timecode_helpers():
    assert format_runtime(75) == "1:15"
    assert format_runtime(3661) == "1:01:01"
    assert seconds_to_timecode(0) == "00:00:00:00"
    assert seconds_to_timecode(1, fps=24) == "00:00:01:00"
    assert seconds_to_srt_timestamp(1.5) == "00:00:01,500"


def test_sequence_report_marks_missing_clips_and_voice(tmp_projects_dir, monkeypatch):
    jobs = tmp_projects_dir.parent / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "data_dir", tmp_projects_dir.parent)

    first = _shot(
        "pending",
        "sht_a",
        dialogue=["Kai: Stay back."],
        duration_s=6,
        camera_angle="from screen left",
    )
    second = _shot(
        "pending",
        "sht_b",
        camera_angle="from screen right",
        refs=[
            ShotRef(role=RefRole.actor, asset_id="act_mia", picture_index=1),
            ShotRef(role=RefRole.scene, asset_id="scn_other", picture_index=2),
        ],
    )
    project = _project_with_shots(first, second)

    report = build_sequence_report(project.id)
    assert report.shot_count == 2
    assert report.clips_ready == 0
    assert report.runtime == "0:12"
    codes = {(issue.code, issue.shot_id) for issue in report.issues}
    assert ("missing_clip", first.id) in codes
    assert ("missing_voice", first.id) in codes
    assert ("axis_jump", second.id) in codes
    assert ("actor_mismatch", second.id) in codes
    assert ("scene_asset_mismatch", second.id) in codes
    ranked = [issue.code for issue in report.issues]
    assert ranked.index("axis_jump") < ranked.index("missing_clip")
    assert ranked.index("actor_mismatch") < ranked.index("missing_clip")


def test_tail_handoff_and_dialogue_overrun(tmp_projects_dir, monkeypatch):
    jobs = tmp_projects_dir.parent / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "data_dir", tmp_projects_dir.parent)

    first = _shot("pending", "sht_a", duration_s=8, status=ShotStatus.succeeded)
    second = _shot(
        "pending",
        "sht_b",
        duration_s=3,
        dialogue=["One.", "Two.", "Three."],
        voice_refs=[
            ShotVoiceRef(asset_id="voice_kai", audio_index=1, speaker="Kai")
        ],
        layout_refs=[
            LayoutReference(
                id="lref_tail",
                origin=ClipTailFrameOrigin(
                    source_shot_id="sht_a",
                    source_job_id="job_src",
                    source_generation=1,
                    output_kind="enhanced",
                    output_key="video",
                    source_filename="video.mp4",
                ),
            )
        ],
    )
    project = _project_with_shots(first, second)
    first = first.model_copy(update={"project_id": project.id})
    second = second.model_copy(
        update={
            "project_id": project.id,
            "layout_refs": [
                LayoutReference(
                    id="lref_tail",
                    origin=ClipTailFrameOrigin(
                        source_shot_id=first.id,
                        source_job_id="job_src",
                        source_generation=1,
                        output_kind="enhanced",
                        output_key="video",
                        source_filename="video.mp4",
                    ),
                )
            ],
        }
    )
    save_shot(first)
    save_shot(second)
    _h3_clip(project.id, first.id)

    report = build_sequence_report(project.id)
    by_id = {entry.shot_id: entry for entry in report.shots}
    assert by_id[first.id].clip_status == SequenceClipStatus.ready
    assert by_id[second.id].has_tail_from_previous is True
    codes = {issue.code for issue in report.issues}
    assert "missing_tail_handoff" not in codes
    assert "dialogue_overrun" in codes
    assert "missing_voice" not in codes


def test_srt_edl_and_csv_follow_storyboard_order(tmp_projects_dir, monkeypatch):
    jobs = tmp_projects_dir.parent / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "data_dir", tmp_projects_dir.parent)

    first = _shot(
        "pending",
        "sht_a",
        title="Entry",
        duration_s=6,
        dialogue=["Kai: Hello."],
        voice_refs=[ShotVoiceRef(asset_id="voice_kai", audio_index=1, speaker="Kai")],
    )
    second = _shot("pending", "sht_b", title="Hold", duration_s=4)
    project = _project_with_shots(first, second)

    report = build_sequence_report(project.id)
    srt = render_srt(report)
    assert "00:00:00,000 --> 00:00:06,000" in srt
    assert "Kai: Hello." in srt
    assert srt.count("-->") == 1

    edl = render_edl(report)
    assert "TITLE:" in edl
    assert "001  AX" in edl
    assert "SHOT: 01 Entry" in edl

    csv = render_shot_list_csv(report)
    assert csv.startswith("index,shot_id,")
    assert "Entry" in csv
    assert "Hold" in csv


def test_sequence_report_uses_pinned_take_not_latest(tmp_projects_dir, monkeypatch):
    from app.core.media.sequence import resolve_shot_clip

    jobs = tmp_projects_dir.parent / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "data_dir", tmp_projects_dir.parent)

    shot = _shot("pending", "sht_a", status=ShotStatus.succeeded)
    project = _project_with_shots(shot)
    shot = shot.model_copy(update={"project_id": project.id})
    older = _h3_clip(
        project.id,
        shot.id,
        filename="take1.mp4",
        created_at="2026-08-01T10:00:00+00:00",
    )
    newer = _h3_clip(
        project.id,
        shot.id,
        filename="take2.mp4",
        created_at="2026-08-01T11:00:00+00:00",
    )
    unpinned = shot.model_copy(update={"h3_job_id": newer})
    save_shot(unpinned)
    latest_clip, latest_status = resolve_shot_clip(project.id, unpinned)
    assert latest_clip is not None
    assert latest_clip.source_job_id == newer
    assert latest_status == SequenceClipStatus.ready

    pinned = unpinned.model_copy(update={"h3_job_id": older})
    save_shot(pinned)
    clip, status = resolve_shot_clip(project.id, pinned)
    assert clip is not None
    assert clip.source_job_id == older
    assert status == SequenceClipStatus.ready

    report = build_sequence_report(project.id)
    assert report.shots[0].clip_job_id == older
    assert report.shots[0].clip_status == SequenceClipStatus.ready
    assert report.clips_ready == 1


def test_sequence_report_falls_back_when_pin_is_missing_or_failed(
    tmp_projects_dir, monkeypatch
):
    jobs = tmp_projects_dir.parent / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "data_dir", tmp_projects_dir.parent)

    shot = _shot("pending", "sht_a", status=ShotStatus.succeeded)
    project = _project_with_shots(shot)
    shot = shot.model_copy(update={"project_id": project.id})
    older = _h3_clip(
        project.id,
        shot.id,
        filename="take1.mp4",
        created_at="2026-08-01T10:00:00+00:00",
    )
    newer = _h3_clip(
        project.id,
        shot.id,
        filename="take2.mp4",
        created_at="2026-08-01T11:00:00+00:00",
    )
    failed = _h3_clip(
        project.id,
        shot.id,
        filename="failed.mp4",
        created_at="2026-08-01T09:00:00+00:00",
        status=JobStatus.failed,
        write_file=False,
    )

    missing_pin = shot.model_copy(update={"h3_job_id": "job_gone"})
    save_shot(missing_pin)
    report = build_sequence_report(project.id)
    assert report.shots[0].clip_job_id == newer

    failed_pin = shot.model_copy(update={"h3_job_id": failed})
    save_shot(failed_pin)
    report = build_sequence_report(project.id)
    assert report.shots[0].clip_job_id == newer
    assert older != newer


def test_sequence_report_pinned_take_stays_ready_when_newer_is_running(
    tmp_projects_dir, monkeypatch
):
    jobs = tmp_projects_dir.parent / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "data_dir", tmp_projects_dir.parent)

    shot = _shot("pending", "sht_a", status=ShotStatus.succeeded)
    project = _project_with_shots(shot)
    shot = shot.model_copy(update={"project_id": project.id})
    older = _h3_clip(
        project.id,
        shot.id,
        filename="take1.mp4",
        created_at="2026-08-01T10:00:00+00:00",
    )
    _h3_clip(
        project.id,
        shot.id,
        filename="take2.mp4",
        created_at="2026-08-01T11:00:00+00:00",
        status=JobStatus.running,
        write_file=False,
    )
    pinned = shot.model_copy(
        update={"h3_job_id": older, "status": ShotStatus.succeeded}
    )
    save_shot(pinned)
    report = build_sequence_report(project.id)
    assert report.shots[0].clip_job_id == older
    assert report.shots[0].clip_status == SequenceClipStatus.ready


def test_assemble_requires_a_succeeded_clip(tmp_projects_dir, monkeypatch):
    jobs = tmp_projects_dir.parent / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "data_dir", tmp_projects_dir.parent)
    project = _project_with_shots(_shot("pending", "sht_a"))

    try:
        assemble_rough_cut(project.id)
    except Exception as exc:
        assert "no succeeded clips" in str(exc)
    else:
        raise AssertionError("expected SequenceError")
