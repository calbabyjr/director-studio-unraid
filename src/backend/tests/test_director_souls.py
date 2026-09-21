from app.agents.director import skill_loader
from app.core.souls.store import (
    create_soul,
    get_soul,
    list_souls,
    record_soul_lesson,
    save_soul,
    soul_prompt_blocks,
    soul_worthy_lesson,
)
from app.core.projects.store import create_project


def test_builtin_souls_seed_and_prompt_blocks(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    souls = list_souls()
    ids = {soul.id for soul in souls}
    assert {"studio", "adult-video", "action", "sci-fi"} <= ids
    adult = get_soul("adult-video")
    assert adult is not None
    assert "explicit" in adult.markdown.lower() or "Adult" in adult.name
    block = soul_prompt_blocks("adult-video")
    assert "<DIRECTOR_SOUL>" in block
    assert "adult-video" in block


def test_custom_soul_edit_and_lessons(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    created = create_soul(name="Horror director", markdown="# Horror\n\nKeep it dark.")
    assert created.id.startswith("horror")
    saved = save_soul(created.id, markdown="# Horror\n\nKeep it dark.\nNever cut on a scream.")
    assert "Never cut on a scream" in saved.markdown
    lesson = record_soul_lesson(created.id, "Hold on the reaction after the scare.", source="auto")
    assert lesson is not None
    block = soul_prompt_blocks(created.id)
    assert "DIRECTOR_LESSONS" in block
    assert "Hold on the reaction" in block


def test_soul_worthy_skips_this_production_facts():
    assert soul_worthy_lesson("Do not create new actors unless asked")
    assert not soul_worthy_lesson("This production is a dungeon, never a warehouse")


def test_with_director_skill_includes_soul(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    core = tmp_path / "DIRECTOR_SKILL.md"
    core.write_text("CORE CONTRACT", encoding="utf-8")
    monkeypatch.setattr(skill_loader, "_skill_path", lambda: core)
    list_souls()
    prompt = skill_loader.with_director_skill("TASK", soul_id="action")
    assert "CORE CONTRACT" in prompt
    assert "<DIRECTOR_SOUL>" in prompt
    assert "Action movie director" in prompt
    assert "TASK" in prompt


def test_project_defaults_to_studio_soul(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = create_project("Film", "A door opens.")
    assert project.soul_id == "studio"
