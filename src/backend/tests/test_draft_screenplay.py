import asyncio

from app.agents.director.chat_orchestrator import sanitize_tools_for_pipeline
from app.agents.director.intent import draft_screenplay_intent, lock_script_intent
from app.agents.director.tool_handlers.project import handle_project_tool
from app.agents.director.tool_schema import director_tool_schemas
from app.core.projects.store import create_project, load_project, save_project


def test_draft_screenplay_intent_ignores_finished_pages():
    pages = "EXT. METRO - NIGHT\n\nMAYA stands in the rain.\n\nMAYA\nOf course.\n"
    assert draft_screenplay_intent(pages) is False
    assert draft_screenplay_intent("Write a screenplay from this premise: two women in a dungeon.") is True
    assert lock_script_intent("That's the script, lock it") is True


def test_draft_pending_hides_planning_tools(tmp_projects_dir):
    project = create_project("Draft", "INT. ROOM - NIGHT\n\nThey wait.")
    save_project(project.model_copy(update={"script_draft_pending": True}))
    project = load_project(project.id)
    names = {
        item["function"]["name"]
        for item in director_tool_schemas(project, current_message="What should we do next?")
    }
    assert "draft_screenplay" in names
    assert "lock_script" in names
    assert "set_script" in names
    assert names.isdisjoint({"plan_shots", "save_storyboard", "queue_h3", "queue_ref_frame"})


def test_premise_message_offers_only_draft_screenplay(tmp_projects_dir):
    project = create_project("Empty", "")
    names = {
        item["function"]["name"]
        for item in director_tool_schemas(
            project,
            current_message="Write a screenplay from this premise: a locked basement.",
        )
    }
    assert names == {"draft_screenplay"}


def test_checkbox_request_offers_only_ask_choices(tmp_projects_dir):
    from app.agents.director.intent import ask_choices_intent

    project = create_project("Locked", "INT. HALL - DAY")
    assert ask_choices_intent("Ask those in multiple-choice format. Remember always to use checkboxes.")
    names = {
        item["function"]["name"]
        for item in director_tool_schemas(
            project,
            current_message="Ask questions in checkboxes.",
        )
    }
    assert names == {"ask_choices"}


def test_ask_choices_is_offered_during_production(tmp_projects_dir):
    from app.core.projects.store import save_project

    project = create_project("Locked", "INT. HALL - DAY")
    save_project(project.model_copy(update={"script_locked": True}))
    names = {
        item["function"]["name"]
        for item in director_tool_schemas(project, current_message="What ending should we use?")
    }
    assert "ask_choices" in names


def test_draft_screenplay_saves_unlocked_and_sanitizer_skips_plan(tmp_projects_dir):
    asyncio.run(_draft_screenplay_saves_unlocked_and_sanitizer_skips_plan())


async def _draft_screenplay_saves_unlocked_and_sanitizer_skips_plan():
    from app.core.projects.store import create_project as _create

    project = _create("Empty", "")
    notes: list[str] = []
    actions: list[str] = []
    handled = await handle_project_tool(
        name="draft_screenplay",
        args={"script": "INT. CELL - NIGHT\n\nJENNY waits.\n\nJENNY\nStay."},
        project_id=project.id,
        project=project,
        svc=None,
        actions=actions,
        notes=notes,
        result_payloads=[],
        user_feedback="",
        requested_minimum_duration_s=4,
        refresh_shots=list,
        storyboard_snapshot=lambda shots: {},
        script_locked_message="locked",
    )
    assert handled is True
    assert actions == ["draft_screenplay"]
    saved = load_project(project.id)
    assert saved.script_draft_pending is True
    assert saved.script_locked is False
    assert "JENNY waits" in saved.script_text

    tools, skipped = sanitize_tools_for_pipeline(
        [
            {"name": "draft_screenplay", "args": {"script": saved.script_text}},
            {"name": "plan_shots", "args": {}},
        ],
        project=saved,
        shots=[],
    )
    names = [item["name"] for item in tools]
    assert "draft_screenplay" in names
    assert "plan_shots" not in names
    assert any("pending approval" in note for note in skipped)


def test_lock_script_clears_draft_gate(tmp_projects_dir):
    asyncio.run(_lock_script_clears_draft_gate())


async def _lock_script_clears_draft_gate():
    project = create_project("Draft", "INT. ROOM - NIGHT")
    save_project(project.model_copy(update={"script_draft_pending": True}))
    project = load_project(project.id)
    actions: list[str] = []
    await handle_project_tool(
        name="lock_script",
        args={},
        project_id=project.id,
        project=project,
        svc=None,
        actions=actions,
        notes=[],
        result_payloads=[],
        user_feedback="",
        requested_minimum_duration_s=4,
        refresh_shots=list,
        storyboard_snapshot=lambda shots: {},
        script_locked_message="locked",
    )
    saved = load_project(project.id)
    assert saved.script_locked is True
    assert saved.script_draft_pending is False
    names = {
        item["function"]["name"]
        for item in director_tool_schemas(saved, current_message="Plan the shots.")
    }
    assert "plan_shots" in names or "save_storyboard" in names
    assert "draft_screenplay" not in names
