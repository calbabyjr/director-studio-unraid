from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.library.store import add_actor_voice_sample, create_external_asset, load_asset
from app.core.projects.store import create_project


def _wav_bytes(*, duration_s: float, sample_rate: int = 16000, channels: int = 1) -> bytes:
    frames = int(duration_s * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"\x00\x00" * frames * channels)
    return buffer.getvalue()


@pytest.fixture
def voice_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    return {"projects": projects, "jobs": jobs, "library": library}


@pytest.fixture
def client(voice_env):
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def test_add_actor_voice_sample_creates_linked_h3_voice(voice_env):
    actor = create_external_asset(
        kind="actors",
        name="Jenny",
        image_bytes=b"\x89PNG\r\n" + b"x" * 80,
        image_filename="master.png",
        project_id=None,
    )
    updated = add_actor_voice_sample(
        actor.id,
        audio_bytes=_wav_bytes(duration_s=2.1),
        audio_filename="jenny.wav",
    )
    assert "voice" in updated.files
    assert updated.files["voice"] == "voice.wav"
    assert updated.meta["linked_voice_ids"]
    voice_id = updated.meta["linked_voice_ids"][0]
    sample = updated.meta["voice_samples"][0]
    assert sample["key"] == "voice"
    assert sample["voice_id"] == voice_id
    assert sample["h3_ready"] is True

    voice = load_asset("voices", voice_id)
    assert voice is not None
    assert voice.name == "Jenny voice"
    assert voice.meta["actor_id"] == actor.id
    assert voice.meta["h3_ready"] is True
    assert voice.files.get("reference") == "reference.wav"

    again = add_actor_voice_sample(
        actor.id,
        audio_bytes=_wav_bytes(duration_s=2.2),
        audio_filename="jenny2.wav",
    )
    assert "voice_2" in again.files
    assert len(again.meta["linked_voice_ids"]) == 2
    assert again.meta["voice_samples"][1]["key"] == "voice_2"


def test_upload_actor_voice_sample_http(client, voice_env):
    project = create_project("Voice project", "Jenny speaks.")
    actor = create_external_asset(
        kind="actors",
        name="Jenny",
        image_bytes=b"\x89PNG\r\n" + b"x" * 80,
        image_filename="master.png",
        project_id=project.id,
    )
    response = client.post(
        f"/api/library/actors/{actor.id}/voice",
        data={"name": "Jenny whisper"},
        files={"file": ("jenny.wav", _wav_bytes(duration_s=2.1), "audio/wav")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == actor.id
    assert "voice" in body["files"]
    voice_id = body["meta"]["linked_voice_ids"][0]
    assert voice_id.startswith("voi_")

    voice_dir = voice_env["projects"] / project.id / "library" / "voices" / voice_id
    assert (voice_dir / "reference.wav").is_file()
    manifest = json.loads((voice_dir / "asset.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "Jenny whisper"
    assert manifest["meta"]["actor_id"] == actor.id

    missing = client.post(
        "/api/library/actors/act_missing/voice",
        files={"file": ("jenny.wav", _wav_bytes(duration_s=2.1), "audio/wav")},
    )
    assert missing.status_code == 404

    too_short = client.post(
        f"/api/library/actors/{actor.id}/voice",
        files={"file": ("short.wav", _wav_bytes(duration_s=1.0), "audio/wav")},
    )
    assert too_short.status_code == 400
    assert "between 2 and 15" in too_short.text
