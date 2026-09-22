"""Production queue pending-id selection and terminal JobStatus handling.

Does not start live Comfy / H3 jobs.
"""

from __future__ import annotations

import pytest

from app.core.h3 import USER_PROMPT_META_KEY
from app.core.h3.prompt import stamp_user_prompt_lock
from app.core.h3.submit import H3SubmitError, H3SubmitOptions
from app.core.projects.layouts import RefRole
from app.core.projects.models import (
    PromptSections,
    Shot,
    ShotRef,
    ShotStatus,
    ShotVoiceRef,
    picture_ref_signature,
    voice_ref_signature,
)
from app.core.projects.shot_queue import (
    _pending_ids,
    cancel_production_queue,
    load_queue,
    on_h3_job_terminal,
    queue_h3_shot,
    save_queue,
    ProductionQueue,
)
from app.core.projects.store import create_project, load_shot, save_project, save_shot
from app.core.schemas import JobRecord, JobStatus


def _seed_shots(statuses: list[tuple[str, ShotStatus]]):
    project = create_project("Queue film", "Jenny waits.")
    shots = []
    for shot_id, status in statuses:
        shot = Shot(
            id=shot_id,
            project_id=project.id,
            scene_id="sc1",
            title=shot_id,
            script_beat="beat",
            duration_s=4,
            status=status,
        )
        save_shot(shot)
        shots.append(shot)
    project.shot_ids = [shot.id for shot in shots]
    save_project(project)
    return project


def test_pending_ids_next_and_remaining_skip_finished_and_active():
    project = _seed_shots(
        [
            ("sht_a", ShotStatus.succeeded),
            ("sht_b", ShotStatus.approved),
            ("sht_c", ShotStatus.succeeded),
            ("sht_d", ShotStatus.draft),
            ("sht_e", ShotStatus.queued),
            ("sht_f", ShotStatus.failed),
        ]
    )
    assert _pending_ids(project.id, mode="next", from_shot_id=None) == ["sht_b"]
    assert _pending_ids(project.id, mode="remaining", from_shot_id=None) == [
        "sht_b",
        "sht_d",
        "sht_f",
    ]
    assert _pending_ids(project.id, mode="next", from_shot_id="sht_b") == ["sht_b"]
    assert _pending_ids(project.id, mode="remaining", from_shot_id="sht_b") == [
        "sht_b",
        "sht_d",
        "sht_f",
    ]
    assert _pending_ids(project.id, mode="remaining", from_shot_id="sht_d") == [
        "sht_d",
        "sht_f",
    ]
    assert _pending_ids(project.id, mode="next", from_shot_id="sht_a") == ["sht_b"]


def test_pending_ids_unknown_shot_raises():
    project = _seed_shots([("sht_a", ShotStatus.draft)])
    with pytest.raises(ValueError, match="shot not found"):
        _pending_ids(project.id, mode="next", from_shot_id="sht_missing")


def test_user_prompt_meta_key_exported():
    assert USER_PROMPT_META_KEY == "user_prompt_sections"


def test_collect_voice_audio_keys_in_index_order():
    from app.core.library.store import write_asset
    from app.core.paths import asset_write_dir
    from app.core.projects.models import ShotVoiceRef
    from app.core.projects.shot_queue import _collect_voice_audio
    from app.core.schemas import LibraryAsset

    project = create_project("Voice queue", "Jenny: wait.")
    voice_dir = asset_write_dir("voices", "voi_jenny", project_id=project.id)
    voice_dir.mkdir(parents=True, exist_ok=True)
    (voice_dir / "reference.wav").write_bytes(b"RIFF-jenny")
    write_asset(
        LibraryAsset(
            id="voi_jenny",
            kind="voices",
            name="Jenny VO",
            pipeline_id="external",
            job_id="",
            created_at="2026-01-01T00:00:00+00:00",
            files={"reference": "reference.wav"},
            meta={"h3_ready": True, "duration_s": 1.5},
            project_id=project.id,
        )
    )
    shot = Shot(
        id="sht_voice",
        project_id=project.id,
        scene_id="sc1",
        title="Hold",
        script_beat="Jenny waits.",
        duration_s=4,
        voice_refs=[
            ShotVoiceRef(asset_id="voi_jenny", audio_index=1, speaker="Jenny"),
        ],
    )
    audio = _collect_voice_audio(shot)
    assert list(audio) == ["voice_audio_1"]
    assert audio["voice_audio_1"] == ("reference.wav", b"RIFF-jenny")


@pytest.mark.asyncio
async def test_on_h3_job_terminal_failed_uses_jobstatus_enum():
    project = create_project("Queue fail", "Jenny waits.")
    save_queue(
        ProductionQueue(
            project_id=project.id,
            mode="remaining",
            status="running",
            current_shot_id="sht_b",
            current_job_id="job_h3_fail",
            pending_shot_ids=["sht_b", "sht_d"],
        )
    )
    job = JobRecord(
        id="job_h3_fail",
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        status=JobStatus.failed,
        name="h3",
        error="boom",
        params={"project_id": project.id, "shot_id": "sht_b"},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    await on_h3_job_terminal(job)
    queue = load_queue(project.id)
    assert queue.status == "failed"
    assert queue.error == "boom"


@pytest.mark.asyncio
async def test_on_h3_job_terminal_success_next_goes_idle(monkeypatch):
    project = create_project("Queue next", "Jenny waits.")
    save_queue(
        ProductionQueue(
            project_id=project.id,
            mode="next",
            status="running",
            current_shot_id="sht_b",
            current_job_id="job_h3_ok",
            pending_shot_ids=["sht_b"],
        )
    )

    async def fail_advance(_queue):
        raise AssertionError("next mode must not advance after success")

    monkeypatch.setattr(
        "app.core.projects.shot_queue._advance_queue", fail_advance
    )
    job = JobRecord(
        id="job_h3_ok",
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        status=JobStatus.succeeded,
        name="h3",
        params={"project_id": project.id, "shot_id": "sht_b"},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    await on_h3_job_terminal(job)
    queue = load_queue(project.id)
    assert queue.status == "idle"
    assert queue.completed_shot_ids == ["sht_b"]
    assert queue.current_job_id is None


def _png_bytes() -> bytes:
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.effect_noise((128, 128), 30).convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _prompt(*, picture: int = 1, audio: int | None = None) -> PromptSections:
    audio_tag = f" <Audio {audio}>" if audio else ""
    return PromptSections(
        subject_definitions=f"Jenny from <Picture {picture}>{audio_tag}.",
        summary="Jenny waits.",
        retention_analysis="Keep Jenny.",
        detailed_description="0-4 seconds: she holds.",
        overall_soundscape="Room tone.",
        non_diegetic_music="None.",
    )


def _seed_actor(project_id: str, asset_id: str = "act_jenny"):
    from app.core.library.store import write_asset
    from app.core.paths import asset_write_dir
    from app.core.schemas import LibraryAsset

    actor_dir = asset_write_dir("actors", asset_id, project_id=project_id)
    actor_dir.mkdir(parents=True, exist_ok=True)
    (actor_dir / "master.png").write_bytes(_png_bytes())
    write_asset(
        LibraryAsset(
            id=asset_id,
            kind="actors",
            name="Jenny",
            pipeline_id="external",
            job_id="",
            created_at="2026-01-01T00:00:00+00:00",
            files={"master": "master.png"},
            project_id=project_id,
        )
    )


def _submittable_shot(project, *, shot_id: str = "sht_hold", meta: dict | None = None) -> Shot:
    _seed_actor(project.id)
    shot = Shot(
        id=shot_id,
        project_id=project.id,
        scene_id="sc1",
        title="Hold",
        script_beat="Jenny waits.",
        duration_s=4,
        status=ShotStatus.approved,
        refs=[
            ShotRef(
                role=RefRole.actor,
                asset_id="act_jenny",
                picture_index=1,
                file_key="master",
            )
        ],
        prompt_sections=_prompt(),
        meta=meta or {},
    )
    meta = dict(shot.meta or {})
    meta.setdefault("prompt_picture_signature", picture_ref_signature(shot.refs))
    shot = shot.model_copy(update={"meta": meta})
    save_shot(shot)
    save_project(project.model_copy(update={"shot_ids": [shot.id]}))
    return shot


@pytest.mark.asyncio
async def test_cancel_production_queue_cancels_inflight_job(monkeypatch):
    project = create_project("Cancel film", "Jenny waits.")
    save_queue(
        ProductionQueue(
            project_id=project.id,
            mode="remaining",
            status="running",
            current_shot_id="sht_b",
            current_job_id="job_h3_run",
            pending_shot_ids=["sht_b", "sht_d"],
        )
    )
    cancelled: list[str] = []

    async def fake_cancel(job_id: str):
        cancelled.append(job_id)
        return None

    monkeypatch.setattr("app.core.jobs.cancel_job", fake_cancel)
    queue = await cancel_production_queue(project.id)
    assert queue.status == "idle"
    assert queue.current_job_id is None
    assert queue.current_shot_id is None
    assert cancelled == ["job_h3_run"]


@pytest.mark.asyncio
async def test_cancel_production_queue_without_job_does_not_call_cancel(monkeypatch):
    project = create_project("Idle cancel", "Jenny waits.")
    save_queue(
        ProductionQueue(
            project_id=project.id,
            status="running",
            pending_shot_ids=["sht_b"],
        )
    )
    cancelled: list[str] = []

    async def fake_cancel(job_id: str):
        cancelled.append(job_id)
        return None

    monkeypatch.setattr("app.core.jobs.cancel_job", fake_cancel)
    queue = await cancel_production_queue(project.id)
    assert queue.status == "idle"
    assert cancelled == []


@pytest.mark.asyncio
async def test_queue_h3_shot_stages_voice_and_default_size():
    from app.core.library.store import write_asset
    from app.core.paths import asset_write_dir
    from app.core.schemas import LibraryAsset

    project = create_project("Queue submit", "Jenny waits.")
    shot = _submittable_shot(project)
    voice_dir = asset_write_dir("voices", "voi_jenny", project_id=project.id)
    voice_dir.mkdir(parents=True, exist_ok=True)
    (voice_dir / "reference.wav").write_bytes(b"RIFF-jenny")
    write_asset(
        LibraryAsset(
            id="voi_jenny",
            kind="voices",
            name="Jenny VO",
            pipeline_id="external",
            job_id="",
            created_at="2026-01-01T00:00:00+00:00",
            files={"reference": "reference.wav"},
            meta={"h3_ready": True, "duration_s": 1.5},
            project_id=project.id,
        )
    )
    voice_refs = [
        ShotVoiceRef(asset_id="voi_jenny", audio_index=1, speaker="Jenny")
    ]
    meta = dict(shot.meta or {})
    meta["prompt_voice_signature"] = voice_ref_signature(voice_refs)
    shot = shot.model_copy(
        update={
            "voice_refs": voice_refs,
            "prompt_sections": _prompt(audio=1),
            "meta": meta,
        }
    )
    save_shot(shot)
    started: list[dict] = []

    async def capture_start(job, *, images=None):
        started.append({"job": job, "images": images})
        return job

    updated = await queue_h3_shot(shot, start_job=capture_start)
    assert updated.status == ShotStatus.queued
    assert updated.h3_job_id
    assert len(started) == 1
    params = started[0]["job"].params
    assert params["width"] == 864
    assert params["height"] == 480
    assert params["audio_keys"] == ["voice_audio_1"]
    assert params["queued_by"] == "production_queue"
    assert started[0]["images"]["voice_audio_1"] == ("reference.wav", b"RIFF-jenny")


@pytest.mark.asyncio
async def test_queue_h3_shot_portrait_and_minimax_key(monkeypatch):
    from app.config import settings

    project = create_project("Portrait", "Vertical 9:16 dungeon.")
    shot = _submittable_shot(project)
    monkeypatch.setattr(settings, "h3_provider", "minimax")
    monkeypatch.setattr(settings, "h3_minimax_api_key", "")
    with pytest.raises(ValueError, match="API key is not configured"):
        await queue_h3_shot(shot, start_job=lambda *a, **k: None)

    monkeypatch.setattr(settings, "h3_minimax_api_key", "test-key")
    started: list[dict] = []

    async def capture_start(job, *, images=None):
        started.append({"job": job, "images": images})
        return job

    updated = await queue_h3_shot(
        shot,
        start_job=capture_start,
    )
    params = started[0]["job"].params
    assert params["h3_provider"] == "minimax"
    assert params["width"] == 480
    assert params["height"] == 864
    assert updated.h3_job_id


@pytest.mark.asyncio
async def test_skip_prompt_refresh_still_blocks_material_review_pending():
    project = create_project("Pending", "Jenny waits.")
    shot = _submittable_shot(
        project,
        meta={"material_review_pending": True, "material_changes": {"added": []}},
    )

    async def fail_start(job, *, images=None):
        raise AssertionError("material review must block before start")

    with pytest.raises(H3SubmitError, match="materials") as exc:
        await queue_h3_shot(shot, skip_prompt_refresh=True, start_job=fail_start)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "material_review_required"


@pytest.mark.asyncio
async def test_locked_prompt_skips_llm_refresh_and_grafts_tags():
    project = create_project("Locked", "Jenny waits.")
    shot = _submittable_shot(project)
    locked_sections = PromptSections(
        subject_definitions="Jenny nude at the left edge, collar only.",
        summary="My locked-off red dungeon establish.",
        retention_analysis="Keep her small.",
        detailed_description="0-4 seconds: one slow step.",
        overall_soundscape="Concrete hum.",
        non_diegetic_music="Cello drone.",
    )
    meta = stamp_user_prompt_lock(shot, locked_sections)
    meta["prompt_picture_signature"] = "stale-signature"
    shot = shot.model_copy(
        update={"prompt_sections": locked_sections, "meta": meta}
    )
    save_shot(shot)

    class BoomService:
        async def write_prompts_after_layout(self, shot_id: str):
            raise AssertionError("locked prompt must not wake write_prompts_after_layout")

    started: list[dict] = []

    async def capture_start(job, *, images=None):
        started.append({"job": job, "images": images})
        return job

    updated = await queue_h3_shot(
        shot,
        director_service=BoomService(),
        start_job=capture_start,
    )
    assert "Jenny nude at the left edge" in updated.prompt_sections.subject_definitions
    assert "<Picture 1>" in updated.prompt_sections.subject_definitions
    assert "My locked-off red dungeon establish." in updated.prompt_sections.summary
    assert started[0]["job"].params["prompt_locked"] is True
    assert "cafe" not in started[0]["job"].params["prompt"].lower()
    # stale picture signature is allowed to remain; lock keeps wording
    assert updated.meta.get("prompt_picture_signature") == "stale-signature"
    assert picture_ref_signature(updated.refs) != "stale-signature"


@pytest.mark.asyncio
async def test_unlocked_stale_signature_refreshes_prompt():
    project = create_project("Stale", "Jenny waits.")
    shot = _submittable_shot(
        project,
        meta={"prompt_picture_signature": "stale-signature"},
    )
    called: list[str] = []

    class RefreshService:
        async def write_prompts_after_layout(self, shot_id: str):
            called.append(shot_id)
            current = load_shot(project.id, shot_id)
            assert current is not None
            fresh = current.prompt_sections.model_copy(
                update={"summary": "fresh material-aware summary"}
            )
            meta = dict(current.meta or {})
            meta["prompt_picture_signature"] = picture_ref_signature(current.refs)
            updated = current.model_copy(update={"prompt_sections": fresh, "meta": meta})
            save_shot(updated)
            return updated

    started: list[dict] = []

    async def capture_start(job, *, images=None):
        started.append({"job": job, "images": images})
        return job

    updated = await queue_h3_shot(
        shot,
        director_service=RefreshService(),
        start_job=capture_start,
    )
    assert called == [shot.id]
    assert "fresh material-aware summary" in started[0]["job"].params["prompt"]
    assert updated.meta["prompt_picture_signature"] != "stale-signature"


@pytest.mark.asyncio
async def test_queue_h3_shot_options_override_size():
    from app.core.h3.submit import submit_h3_shot

    project = create_project("Sized", "Jenny waits.")
    shot = _submittable_shot(project)
    started: list[dict] = []

    async def capture_start(job, *, images=None):
        started.append({"job": job, "images": images})
        return job

    await submit_h3_shot(
        shot,
        options=H3SubmitOptions(width=1280, height=704),
        start_job=capture_start,
        queued_by="production_queue",
    )
    assert started[0]["job"].params["width"] == 1280
    assert started[0]["job"].params["height"] == 704


@pytest.mark.asyncio
async def test_remaining_tail_frame_uses_pinned_take(monkeypatch):
    project = create_project("Queue pin tail", "Jenny waits.")
    source = Shot(
        id="sht_b",
        project_id=project.id,
        scene_id="sc1",
        title="Hold",
        script_beat="beat",
        duration_s=4,
        status=ShotStatus.succeeded,
        h3_job_id="job_pinned_old",
    )
    save_shot(source)
    save_queue(
        ProductionQueue(
            project_id=project.id,
            mode="remaining",
            status="running",
            current_shot_id="sht_b",
            current_job_id="job_h3_new",
            pending_shot_ids=["sht_b", "sht_d"],
            chain_tail_frames=True,
        )
    )

    captured: list[str] = []

    def fake_extract(**kwargs):
        captured.append(kwargs["source_job_id"])
        return {}

    async def fake_advance(queue):
        return queue

    monkeypatch.setattr(
        "app.core.projects.shot_queue.extract_clip_tail_frame", fake_extract
    )
    monkeypatch.setattr("app.core.projects.shot_queue._advance_queue", fake_advance)
    job = JobRecord(
        id="job_h3_new",
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        status=JobStatus.succeeded,
        name="h3",
        params={"project_id": project.id, "shot_id": "sht_b"},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    await on_h3_job_terminal(job)
    assert captured == ["job_pinned_old"]


@pytest.mark.asyncio
async def test_remaining_tail_frame_falls_back_when_pin_missing(monkeypatch):
    project = create_project("Queue pin missing", "Jenny waits.")
    source = Shot(
        id="sht_b",
        project_id=project.id,
        scene_id="sc1",
        title="Hold",
        script_beat="beat",
        duration_s=4,
        status=ShotStatus.succeeded,
        h3_job_id="job_pinned_gone",
    )
    save_shot(source)
    save_queue(
        ProductionQueue(
            project_id=project.id,
            mode="remaining",
            status="running",
            current_shot_id="sht_b",
            current_job_id="job_h3_new",
            pending_shot_ids=["sht_b", "sht_d"],
            chain_tail_frames=True,
        )
    )

    captured: list[str] = []

    def fake_extract(**kwargs):
        source_job_id = kwargs["source_job_id"]
        if source_job_id == "job_pinned_gone":
            raise ValueError("pinned take missing")
        captured.append(source_job_id)
        return {}

    async def fake_advance(queue):
        return queue

    monkeypatch.setattr(
        "app.core.projects.shot_queue.extract_clip_tail_frame", fake_extract
    )
    monkeypatch.setattr("app.core.projects.shot_queue._advance_queue", fake_advance)
    job = JobRecord(
        id="job_h3_new",
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        status=JobStatus.succeeded,
        name="h3",
        params={"project_id": project.id, "shot_id": "sht_b"},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    await on_h3_job_terminal(job)
    assert captured == ["job_h3_new"]
