from fastapi.testclient import TestClient

from app.agents.director import skill_loader
from app.core.projects.store import create_project
from app.core.workspace.store import (
    delete_file,
    get_file,
    list_files,
    save_file,
    workspace_prompt_blocks,
)
from app.core.workspace.templates import AGENTS_FILENAME, USER_FILENAME, USER_TEMPLATE
from app.main import create_app


def test_global_defaults_are_placeholders_and_stay_out_of_the_prompt(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    files = list_files("global")
    names = {item.name for item in files}
    assert {USER_FILENAME, AGENTS_FILENAME} <= names
    user = get_file("user.md", "global")
    assert user is not None
    assert user.reserved
    assert user.placeholder
    assert user.markdown.strip() == USER_TEMPLATE.strip()
    assert workspace_prompt_blocks() == ""


def test_edited_user_md_and_extra_files_are_injected(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    save_file("user.md", "# User\n\nCall me Cal.\nNever invent extra performers.\n", scope="global")
    save_file(
        "house-style.md",
        "# House style\n\nKeep wardrobe continuity across shots.\n",
        scope="global",
        create=True,
    )
    block = workspace_prompt_blocks()
    assert "<USER>" in block
    assert "Call me Cal." in block
    assert "</USER>" in block
    assert '<DIRECTOR_WORKSPACE file="house-style.md" scope="director" soul="studio">' in block
    assert "wardrobe continuity" in block
    assert "</DIRECTOR_WORKSPACE>" in block
    assert "How to address you" not in block


def test_project_workspace_outranks_global_in_prompt_order(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = create_project("Film", "A door opens.")
    save_file(
        "AGENTS.md",
        "# Studio\n\nAlways shoot handheld.\n",
        scope="global",
    )
    save_file(
        "AGENTS.md",
        "# This production\n\nLock off the camera.\n",
        scope="project",
        project_id=project.id,
    )
    block = workspace_prompt_blocks(project.id)
    assert block.index("Always shoot handheld") < block.index("Lock off the camera")
    assert 'scope="project"' in block


def test_director_workspace_files_are_isolated_per_soul(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    save_file("AGENTS.md", "# Studio\n\nHandheld only.\n", scope="global", soul_id="studio")
    save_file("AGENTS.md", "# Adult\n\nKeep identities exact.\n", scope="global", soul_id="adult-video")
    studio = workspace_prompt_blocks(soul_id="studio")
    adult = workspace_prompt_blocks(soul_id="adult-video")
    assert "Handheld only" in studio
    assert "Keep identities exact" not in studio
    assert "Keep identities exact" in adult
    assert "Handheld only" not in adult
    assert 'soul="studio"' in studio
    assert 'soul="adult-video"' in adult


def test_reserved_files_cannot_be_deleted(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    list_files("global")
    try:
        delete_file("user.md", "global")
        raise AssertionError("user.md should be reserved")
    except ValueError as exc:
        assert "cannot delete" in str(exc)


def test_with_director_skill_includes_user_md(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    core = tmp_path / "DIRECTOR_SKILL.md"
    core.write_text("CORE CONTRACT", encoding="utf-8")
    monkeypatch.setattr(skill_loader, "_skill_path", lambda: core)
    save_file("user.md", "# User\n\nI prefer tight coverage.\n", scope="global")
    prompt = skill_loader.with_director_skill("TASK", soul_id="studio")
    assert "CORE CONTRACT" in prompt
    assert "<USER>" in prompt
    assert "tight coverage" in prompt
    assert prompt.index("<USER>") < prompt.index("<DIRECTOR_SOUL>")
    assert prompt.index("<DIRECTOR_SOUL>") < prompt.index("TASK")


def test_workspace_api_round_trip(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    with TestClient(create_app()) as client:
        listed = client.get("/api/workspace")
        assert listed.status_code == 200
        names = {item["name"] for item in listed.json()}
        assert "user.md" in names

        saved = client.put(
            "/api/workspace/user.md",
            json={"markdown": "# User\n\nCall me Cal.\n", "scope": "global"},
        )
        assert saved.status_code == 200
        assert "Call me Cal." in saved.json()["markdown"]
        assert saved.json()["placeholder"] is False

        created = client.post(
            "/api/workspace",
            json={"name": "continuity.md", "markdown": "# Continuity\n\nMatch eyelines.\n"},
        )
        assert created.status_code == 200
        assert created.json()["name"] == "continuity.md"

        forbidden = client.delete("/api/workspace/user.md")
        assert forbidden.status_code == 400

        project = create_project("Film", "A door opens.")
        project_file = client.put(
            "/api/workspace/AGENTS.md",
            json={
                "markdown": "# This production\n\nNight interior only.\n",
                "scope": "project",
                "project_id": project.id,
            },
        )
        assert project_file.status_code == 200
        listed_project = client.get(
            "/api/workspace",
            params={"scope": "project", "project_id": project.id},
        )
        assert listed_project.status_code == 200
        assert any(item["name"] == "AGENTS.md" for item in listed_project.json())
        assert "Night interior only." in listed_project.json()[0]["markdown"]
