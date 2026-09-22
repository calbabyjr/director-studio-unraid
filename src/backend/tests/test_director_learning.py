from app.core.projects.director_learning import (
    extract_turn_lessons,
    learn_from_turn,
    read_memory_md,
    retract_lesson,
)
from app.core.projects.director_memory import add_note, apply_memory_to_system, forget_note
from app.core.projects.store import create_project, save_project


def test_remember_in_the_future_does_not_store_a_truncated_fragment():
    from app.core.projects.director_learning import extract_turn_lessons

    lessons = extract_turn_lessons(
        "YES, I told you to continue. Remember that in the future"
    )
    texts = [text.lower() for text, _scope in lessons]
    assert not any(item.startswith("to continue") for item in texts)
    assert any("yes" in item and "continue" in item for item in texts)


def test_correction_lessons_include_i_told_you_and_you_keep():
    told = extract_turn_lessons("I already told you never create new actors unless I ask.")
    assert any("never create" in text.lower() for text, _scope in told)
    keep = extract_turn_lessons("You keep inventing extra performers.")
    assert any("inventing extra performers" in text.lower() for text, scope in keep if scope == "global")
    no_lead = extract_turn_lessons("No. It is a dungeon, not a warehouse.")
    assert any("dungeon" in text.lower() for text, _scope in no_lead)


def test_learn_from_turn_writes_permanent_memory_md(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = create_project("Learning film", "Jenny walks.")
    notes = learn_from_turn(
        project.id,
        user_message="No. It is a dungeon, not a warehouse.",
    )
    assert notes
    project_md = read_memory_md("project", project.id)
    assert "dungeon" in project_md.lower()
    system = apply_memory_to_system("You are the Director.", project.id)
    assert "<DIRECTOR_MEMORY" in system
    assert "dungeon" in system


def test_forget_retracts_permanent_memory(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = create_project("Forget film", "Jenny walks.")
    note = add_note(
        text="Never invent extra performers.",
        scope="global",
        source="user",
        project_id=project.id,
    )
    assert "Never invent extra performers" in read_memory_md("global")
    removed = forget_note(note.id, project_id=project.id)
    assert removed is not None
    assert "Never invent extra performers" not in read_memory_md("global")


def test_director_memory_is_isolated_per_soul(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    studio = create_project("Studio film", "A door opens.")
    adult = create_project("Adult film", "A door opens.")
    adult.soul_id = "adult-video"
    save_project(adult)
    add_note(
        text="Never invent extra performers.",
        scope="global",
        source="user",
        project_id=adult.id,
        soul_id="adult-video",
    )
    assert "Never invent extra performers" in read_memory_md("global", soul_id="adult-video")
    assert "Never invent extra performers" not in read_memory_md("global", soul_id="studio")
    studio_system = apply_memory_to_system("You are the Director.", studio.id)
    adult_system = apply_memory_to_system("You are the Director.", adult.id)
    assert "Never invent extra performers" in adult_system
    assert "Never invent extra performers" not in studio_system


def test_retract_lesson_is_idempotent(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert retract_lesson("nothing here yet", scope="global") is False
