from app.core.projects.chat_history import load_chat_history
from app.core.projects.director_patrol import (
    collect_open_tasks,
    open_checkbox_items,
    patrol_project,
    run_patrol,
    sync_board_tasks_file,
)
from app.core.projects.store import create_project
from app.core.workspace.store import save_file


def test_open_checkbox_items_ignore_done_and_empty():
    markdown = """# Tasks

- [ ] Finish Mia wardrobe stills
- [x] Cast the lead
- [ ]
- [ ] Lock the dungeon geography
"""
    items = open_checkbox_items(markdown)
    assert items == ["Finish Mia wardrobe stills", "Lock the dungeon geography"]


def test_sync_board_tasks_file_lists_shots_that_need_h3(tmp_path, monkeypatch):
    from app.config import settings
    from app.core.projects.models import PromptSections, Shot, ShotStatus
    from app.core.projects.store import save_project, save_shot
    from app.core.workspace.store import get_file

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = create_project("Task film", "A door opens.")
    shot = Shot(
        id="sht_task_1",
        project_id=project.id,
        scene_id="sc01",
        title="The Threshold",
        script_beat="Wendy enters.",
        duration_s=4.0,
        status=ShotStatus.needs_review,
        prompt_sections=PromptSections(summary="Locked-off dungeon two-shot."),
    )
    save_shot(shot)
    save_project(project.model_copy(update={"shot_ids": [shot.id]}))
    lines = sync_board_tasks_file(project.id)
    assert any("The Threshold" in line for line in lines)
    stored = get_file("TASKS.md", "project", project.id)
    assert stored is not None
    assert "- [ ] Generate H3 video for The Threshold" in stored.markdown


def test_collect_open_tasks_from_director_tasks_md(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = create_project("Patrol film", "A door opens.")
    save_file(
        "TASKS.md",
        "# Tasks\n\n- [ ] Finish Mia wardrobe stills\n- [x] Cast the lead\n",
        scope="global",
        soul_id="studio",
    )
    tasks = collect_open_tasks(project.id, "studio")
    assert any("Mia wardrobe" in task.text for task in tasks)
    assert not any("Cast the lead" in task.text for task in tasks)


def test_patrol_posts_once_then_skips_unchanged(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = create_project("Patrol film", "A door opens.")
    save_file(
        "TASKS.md",
        "# Tasks\n\n- [ ] Need to recast the hallway\n",
        scope="project",
        project_id=project.id,
    )
    first = patrol_project(project.id)
    assert first.posted is True
    assert any("hallway" in text.lower() for text in first.tasks)
    history = load_chat_history(project.id)
    assert history
    assert history[-1].content.startswith("Memory check —")
    second = patrol_project(project.id)
    assert second.posted is False
    assert second.skipped == "unchanged"
    assert len(load_chat_history(project.id)) == 1


def test_run_patrol_covers_all_projects(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    create_project("Empty film", "A door opens.")
    report = run_patrol()
    assert report.projects
    assert report.ran_at
