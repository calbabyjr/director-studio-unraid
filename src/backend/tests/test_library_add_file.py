from app.core.library.store import add_asset_file, create_external_asset, delete_asset_file


def test_add_face_and_profile_to_actor(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "library_root", tmp_path / "library")
    actor = create_external_asset(
        kind="actors",
        name="Jenny",
        image_bytes=b"\x89PNG\r\n" + b"x" * 80,
        image_filename="master.png",
        project_id=None,
    )
    updated = add_asset_file(
        "actors",
        actor.id,
        data=b"\x89PNG\r\n" + b"y" * 80,
        filename="face.jpg",
        file_key="face",
    )
    assert "face" in updated.files
    assert updated.files["master"]
    again = add_asset_file(
        "actors",
        actor.id,
        data=b"\x89PNG\r\n" + b"z" * 80,
        filename="face2.jpg",
        file_key="face",
    )
    assert "face_2" in again.files


def test_delete_face_jpg_keeps_master(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "library_root", tmp_path / "library")
    actor = create_external_asset(
        kind="actors",
        name="Jenny",
        image_bytes=b"\x89PNG\r\n" + b"x" * 80,
        image_filename="master.png",
        project_id=None,
    )
    with_face = add_asset_file(
        "actors",
        actor.id,
        data=b"\xff\xd8" + b"y" * 80,
        filename="clothed.jpg",
        file_key="face",
    )
    face_name = with_face.files["face"]
    adir = tmp_path / "library" / "actors" / actor.id
    assert (adir / face_name).is_file()
    updated = delete_asset_file("actors", actor.id, "face")
    assert "face" not in (updated.files or {})
    assert updated.files["master"]
    assert not (adir / face_name).exists()
    assert (adir / updated.files["master"]).is_file()
    extras = (updated.meta or {}).get("extra_views") or []
    assert not any(isinstance(item, dict) and item.get("key") == "face" for item in extras)
