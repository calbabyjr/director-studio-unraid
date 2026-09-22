from app.core.jobs.shot_sync import on_pipeline_job_terminal
from app.core.projects.director_memory import load_notes
from app.core.projects.director_reflection import (
    ReflectionEvent,
    deterministic_lessons,
    reflect_on_event,
    reflect_on_tool_failure,
)
from app.core.projects.store import create_project
from app.core.schemas import JobRecord, JobStatus
from app.core.souls.store import get_soul


def test_append_shot_string_error_becomes_a_soul_lesson():
    lessons = deterministic_lessons(
        ReflectionEvent(
            kind="tool_failed",
            project_id="prj_x",
            tool_name="append_shot",
            error="Input should be a valid dictionary or instance of NewShotDraft input_type=str",
            status="failed",
        )
    )
    assert any("JSON object" in item.text for item in lessons)
    assert all(item.scope == "soul" for item in lessons)


def test_failed_h3_job_teaches_not_to_fake_a_queue():
    lessons = deterministic_lessons(
        ReflectionEvent(
            kind="job",
            project_id="prj_x",
            pipeline_id="h3_ref2va",
            job_name="h3:The Threshold",
            status="failed",
            error="RuntimeError sageattention",
        )
    )
    texts = " ".join(item.text for item in lessons)
    assert "sageattention" in texts.lower()
    assert "queued" in texts.lower()


def test_successful_h3_clip_keeps_picture_bindings():
    lessons = deterministic_lessons(
        ReflectionEvent(
            kind="h3_clip",
            project_id="prj_x",
            pipeline_id="h3_ref2va",
            job_name="h3:Establish the Space",
            status="succeeded",
            shot_title="Establish the Space",
        )
    )
    assert any("Picture bindings" in item.text for item in lessons)
    assert lessons[0].scope == "project"


def test_reflect_on_tool_failure_writes_memory(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "director_reflect_with_llm", False)
    project = create_project("Reflect film", "Jenny walks.")
    written = reflect_on_tool_failure(
        project_id=project.id,
        tool_name="append_shot",
        error="Input should be a valid dictionary input_type=str",
    )
    assert written
    notes = load_notes(project.id)
    assert any("JSON object" in note.text for note in notes)
    soul = get_soul("studio")
    assert soul is not None
    assert any("JSON object" in lesson.text for lesson in soul.lessons)


def test_job_terminal_hook_records_a_failed_h3_lesson(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "jobs_dir", tmp_path / "jobs")
    monkeypatch.setattr(settings, "director_reflect_with_llm", False)
    project = create_project("H3 fail film", "Jenny walks.")
    job = JobRecord(
        id="job_reflect_fail",
        pipeline_id="h3_ref2va",
        status=JobStatus.failed,
        name="h3:The Whip",
        error="RuntimeError sageattention",
        created_at="2026-09-22T00:00:00+00:00",
        updated_at="2026-09-22T00:00:00+00:00",
        project_id=project.id,
        params={"shot_id": "sht_x", "shot_title": "The Whip"},
    )
    on_pipeline_job_terminal(job)
    notes = load_notes(project.id)
    assert any("sageattention" in note.text.lower() for note in notes)
