from app.core.projects.director_memory import (
    add_note,
    apply_memory_to_system,
    capture_user_memory,
    extract_memory_candidates,
    forget_note,
    load_notes,
    memory_prompt_block,
)
from app.core.projects.store import create_project


def test_extracts_production_rules_and_corrections():
    assert any(
        "dungeon" in item.lower() and "warehouse" in item.lower()
        for item in extract_memory_candidates(
            "It is not a warehouse, it is a dungeon."
        )
    )
    assert any(
        "warehouse" in item.lower()
        for item in extract_memory_candidates(
            "Remove any references to a concrete warehouse in this production"
        )
    )
    remembered = extract_memory_candidates(
        "Remember never create new actors unless I ask."
    )
    assert remembered
    assert not extract_memory_candidates("retry")
    assert not extract_memory_candidates("Do you want option A or B?")
    assert not extract_memory_candidates("Do not queue generation yet")
    future = extract_memory_candidates(
        'YES, I told you to continue. Remember that in the future'
    )
    assert any("continue" in item.lower() and "yes" in item.lower() for item in future)
    assert not any(item.lower().startswith("to continue") for item in future)
    assert not extract_memory_candidates(
        "Shot 01 references changed. Saved reference delta: {}. Do not infer unrequested production actions."
    )


def test_project_and_global_notes_persist_across_loads(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = create_project("Memory film", "Jenny walks.")

    project_note = add_note(
        text="This production is a dungeon, never a warehouse.",
        scope="project",
        source="user",
        project_id=project.id,
    )
    global_note = add_note(
        text="Do not create new actors unless asked.",
        scope="global",
        source="user",
        project_id=project.id,
    )
    notes = load_notes(project.id)
    assert {note.id for note in notes} == {project_note.id, global_note.id}
    block = memory_prompt_block(project.id)
    assert "dungeon" in block
    assert "all projects" in block
    system = apply_memory_to_system("You are the Director.", project.id)
    assert "dungeon" in system
    assert "DIRECTOR_MEMORY" in system or "STANDING_NOTES" in system
    removed = forget_note(project_note.id, project_id=project.id)
    assert removed is not None
    assert all(note.id != project_note.id for note in load_notes(project.id))


def test_capture_bootstraps_from_existing_chat(tmp_path, monkeypatch):
    from app.config import settings
    from app.core.projects.chat_history import append_chat_message

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = create_project("Old chat", "Script.")
    append_chat_message(
        project.id,
        role="user",
        content="It is not a warehouse, it is a dungeon.",
    )
    capture_user_memory(project.id, "retry")
    texts = [note.text.lower() for note in load_notes(project.id)]
    assert any("dungeon" in text for text in texts)
