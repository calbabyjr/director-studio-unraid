from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.projects.layouts import RefRole
from app.core.projects.models import Shot, ShotRef, ShotStatus
from app.core.projects.store import create_project, load_shot, save_project, save_shot


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    projects = tmp_path / "projects"
    jobs = tmp_path / "jobs"
    library = tmp_path / "library"
    projects.mkdir()
    jobs.mkdir()
    library.mkdir()
    monkeypatch.setattr(settings, "projects_dir", projects)
    monkeypatch.setattr(settings, "jobs_dir", jobs)
    monkeypatch.setattr(settings, "library_root", library)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def test_recast_prop_to_costume_moves_files_and_shot_role(client, tmp_path: Path):
    project = create_project("Wardrobe", "A red coat on the chair.")
    imported = client.post(
        "/api/library/import",
        data={
            "kind": "props",
            "name": "Red coat",
            "notes": "Should have been a costume",
            "project_id": project.id,
        },
        files={"file": ("coat.jpg", b"fake-coat-jpg" * 200, "image/jpeg")},
    )
    assert imported.status_code == 200, imported.text
    prop = imported.json()
    asset_id = prop["id"]
    shot = Shot(
        id="sht_recast1",
        project_id=project.id,
        scene_id="sc01",
        title="Coat",
        script_beat="She puts on the coat.",
        duration_s=8.0,
        status=ShotStatus.draft,
        refs=[ShotRef(role=RefRole.prop, asset_id=asset_id, picture_index=1, file_key="master")],
    )
    save_shot(shot)
    project.shot_ids = [shot.id]
    save_project(project)

    moved = client.post(
        f"/api/library/props/{asset_id}/kind",
        json={"kind": "costumes"},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["id"] == asset_id
    assert body["kind"] == "costumes"
    assert body["name"] == "Red coat"
    assert body["meta"]["recast_from"] == "props"
    assert body["urls"]["master"].startswith(f"/api/files/library/costumes/{asset_id}/")

    prop_dir = tmp_path / "projects" / project.id / "library" / "props" / asset_id
    costume_dir = tmp_path / "projects" / project.id / "library" / "costumes" / asset_id
    assert not prop_dir.exists()
    assert (costume_dir / "master.jpg").exists()

    assert client.get(f"/api/library/props/{asset_id}").status_code == 404
    fetched = client.get(f"/api/library/costumes/{asset_id}")
    assert fetched.status_code == 200
    assert fetched.json()["kind"] == "costumes"

    listed_costumes = client.get("/api/library", params={"kind": "costumes", "project_id": project.id})
    assert any(item["id"] == asset_id for item in listed_costumes.json())
    listed_props = client.get("/api/library", params={"kind": "props", "project_id": project.id})
    assert listed_props.json() == []

    updated_shot = load_shot(project.id, shot.id)
    assert updated_shot is not None
    assert updated_shot.refs[0].role == RefRole.costume
    assert updated_shot.refs[0].asset_id == asset_id
    assert updated_shot.meta.get("material_review_pending") is True


def test_recast_rejects_actor_to_costume(client):
    project = create_project("Cast", "A lead.")
    imported = client.post(
        "/api/library/import",
        data={"kind": "actors", "name": "Mara", "project_id": project.id},
        files={"file": ("mara.png", b"fake-actor-png" * 200, "image/png")},
    )
    assert imported.status_code == 200, imported.text
    actor_id = imported.json()["id"]
    response = client.post(
        f"/api/library/actors/{actor_id}/kind",
        json={"kind": "costumes"},
    )
    assert response.status_code == 400
    assert "props" in response.json()["detail"]
