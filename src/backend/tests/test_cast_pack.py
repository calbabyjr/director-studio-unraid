import pytest

from app.core.library.store import create_external_asset, write_asset
from app.core.paths import asset_write_dir
from app.core.projects.cast_pack import actor_pack_status, cast_actor_on_shot
from app.core.projects.layouts import RefRole
from app.core.projects.models import Shot, ShotRef, ShotVoiceRef
from app.core.schemas import LibraryAsset


def test_cast_actor_binds_extra_views(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "library_root", tmp_path / "library")
    actor = create_external_asset(
        kind="actors",
        name="Jenny",
        image_bytes=b"\x89PNG\r\n" + b"x" * 80,
        image_filename="master.png",
        project_id="prj_1",
    )
    files = dict(actor.files)
    files["face"] = "face.png"
    files["profile"] = "profile.png"
    actor = write_asset(actor.model_copy(update={"files": files}))
    shot = Shot(
        id="sht_1",
        project_id="prj_1",
        scene_id="sc_1",
        title="Establish",
        script_beat="Jenny enters.",
        duration_s=8,
        refs=[
            ShotRef(role=RefRole.scene, asset_id="scn_room", picture_index=1, file_key="master"),
        ],
    )
    updated = cast_actor_on_shot(shot, actor.id)
    actor_refs = [ref for ref in updated.refs if ref.role == RefRole.actor]
    assert {ref.file_key for ref in actor_refs} == {"master", "face", "profile"}
    assert [ref.picture_index for ref in updated.refs] == list(range(1, len(updated.refs) + 1))
    pack = actor_pack_status(actor)
    assert pack["view_count"] == 3
    assert pack["ready"] is True
    assert pack["has_voice"] is False


def test_cast_actor_binds_linked_h3_voice(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "library_root", tmp_path / "library")
    actor = create_external_asset(
        kind="actors",
        name="Jenny",
        image_bytes=b"\x89PNG\r\n" + b"x" * 80,
        image_filename="master.png",
        project_id="prj_1",
    )
    voice_dir = asset_write_dir("voices", "voi_jenny", project_id="prj_1")
    voice_dir.mkdir(parents=True, exist_ok=True)
    (voice_dir / "reference.wav").write_bytes(b"RIFF-fake")
    write_asset(
        LibraryAsset(
            id="voi_jenny",
            kind="voices",
            name="Jenny VO",
            pipeline_id="external",
            job_id="",
            created_at="2026-01-01T00:00:00+00:00",
            files={"reference": "reference.wav"},
            meta={"h3_ready": True, "duration_s": 2.0},
            project_id="prj_1",
        )
    )
    actor = write_asset(
        actor.model_copy(update={"meta": {**actor.meta, "linked_voice_ids": ["voi_jenny"]}})
    )
    shot = Shot(
        id="sht_1",
        project_id="prj_1",
        scene_id="sc_1",
        title="Establish",
        script_beat="Jenny enters.",
        duration_s=8,
        refs=[
            ShotRef(role=RefRole.scene, asset_id="scn_room", picture_index=1, file_key="master"),
        ],
        voice_refs=[
            ShotVoiceRef(asset_id="voi_other", audio_index=1, speaker="Other"),
        ],
    )
    updated = cast_actor_on_shot(shot, actor.id)
    assert [ref.asset_id for ref in updated.voice_refs] == ["voi_other", "voi_jenny"]
    assert updated.voice_refs[1].speaker == "Jenny"
    assert updated.voice_refs[1].audio_index == 2
    pack = actor_pack_status(actor)
    assert pack["has_voice"] is True
    assert pack["linked_voice_ids"] == ["voi_jenny"]


def test_cast_actor_rejects_missing_actor(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "library_root", tmp_path / "library")
    shot = Shot(
        id="sht_1",
        project_id="prj_1",
        scene_id="sc_1",
        title="Establish",
        script_beat="Empty.",
        duration_s=4,
    )
    with pytest.raises(ValueError, match="actor not found"):
        cast_actor_on_shot(shot, "act_missing")
