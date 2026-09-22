from app.core.library.actor_sheet import pack_actor_sheet_images
from app.core.library.store import create_external_asset, write_asset
from app.core.paths import find_asset_dir


def test_pack_actor_sheet_uses_master_and_extra_views(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "library_root", tmp_path / "library")
    actor = create_external_asset(
        kind="actors",
        name="Jenny",
        image_bytes=b"\x89PNG\r\n" + b"m" * 80,
        image_filename="master.png",
        project_id="prj_1",
    )
    adir = find_asset_dir("actors", actor.id)
    assert adir is not None
    (adir / "face.png").write_bytes(b"\x89PNG\r\n" + b"f" * 80)
    (adir / "profile.png").write_bytes(b"\x89PNG\r\n" + b"p" * 80)
    files = dict(actor.files)
    files["face"] = "face.png"
    files["profile"] = "profile.png"
    actor = write_asset(actor.model_copy(update={"files": files}))
    packed = pack_actor_sheet_images(actor)
    assert "actor" in packed
    assert packed["actor"][0].endswith(".png")
    assert "face" in packed
    assert "profile" in packed
    assert "wardrobe" not in packed


def test_pack_actor_sheet_ignores_generated_wardrobe_ref(tmp_path, monkeypatch):
    from app.config import settings
    from app.core.library.actor_sheet import PRESERVE_DRESS_DESCRIPTION

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "library_root", tmp_path / "library")
    actor = create_external_asset(
        kind="actors",
        name="Jenny",
        image_bytes=b"\x89PNG\r\n" + b"m" * 80,
        image_filename="master.png",
        project_id="prj_1",
    )
    adir = find_asset_dir("actors", actor.id)
    assert adir is not None
    (adir / "wardrobe_ref.png").write_bytes(b"\x89PNG\r\n" + b"w" * 80)
    files = dict(actor.files)
    files["wardrobe_ref"] = "wardrobe_ref.png"
    actor = write_asset(actor.model_copy(update={"files": files}))
    packed = pack_actor_sheet_images(actor)
    assert "wardrobe" not in packed
    assert "fully nude" in PRESERVE_DRESS_DESCRIPTION


def test_pack_actor_sheet_rejects_empty_actor(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "library_root", tmp_path / "library")
    actor = create_external_asset(
        kind="actors",
        name="Empty",
        image_bytes=b"\x89PNG\r\n" + b"m" * 80,
        image_filename="master.png",
        project_id=None,
    )
    adir = find_asset_dir("actors", actor.id)
    assert adir is not None
    for path in adir.iterdir():
        if path.suffix == ".png":
            path.unlink()
    actor = write_asset(actor.model_copy(update={"files": {}}))
    try:
        pack_actor_sheet_images(actor)
    except ValueError as exc:
        assert "still" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
