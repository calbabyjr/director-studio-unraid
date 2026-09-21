"""Director native tools for sequence review and assembly."""

from __future__ import annotations

import pytest

from app.agents.director.chat import DIRECTOR_TOOL_SCHEMAS, _run_tools
from app.agents.director.intent import assemble_sequence_intent, sequence_review_intent
from app.agents.director.tool_schema import director_chat_guides, director_tool_schemas
from app.core.projects.layouts import RefRole
from app.core.projects.models import PromptSections, Shot, ShotRef, ShotStatus
from app.core.projects.store import create_project, save_project, save_shot


def _prompt() -> PromptSections:
    return PromptSections(
        subject_definitions="subject",
        summary="summary",
        retention_analysis="retention",
        detailed_description="detailed",
        overall_soundscape="sound",
        non_diegetic_music="music",
    )


def test_sequence_tools_are_in_the_catalog():
    names = {item["function"]["name"] for item in DIRECTOR_TOOL_SCHEMAS}
    assert "review_sequence" in names
    assert "assemble_sequence" in names


def test_assemble_sequence_is_offered_only_on_explicit_request(tmp_projects_dir):
    project = create_project("Cut", "A door opens.")
    offered = {
        tool["function"]["name"]
        for tool in director_tool_schemas(project, current_message="How is the storyboard?")
    }
    assert "review_sequence" in offered
    assert "assemble_sequence" not in offered

    assemble_offered = {
        tool["function"]["name"]
        for tool in director_tool_schemas(
            project, current_message="Assemble a rough cut from the clips."
        )
    }
    assert "assemble_sequence" in assemble_offered
    assert "review_sequence" in assemble_offered


def test_sequence_review_intent_and_guide(tmp_projects_dir):
    assert sequence_review_intent("Check continuity across the cut")
    assert assemble_sequence_intent("stitch the clips into a rough cut")
    assert not assemble_sequence_intent("what is the continuity like")

    project = create_project("Cut", "A door opens.")
    guides = director_chat_guides(
        project, include_visual_qc=False, current_message="Check the continuity"
    )
    assert "sequence-assembly" in guides


@pytest.mark.asyncio
async def test_review_sequence_tool_reports_runtime(tmp_projects_dir):
    project = create_project("Cut", "INT. HALL")
    shot = Shot(
        id="sht_entry",
        project_id=project.id,
        scene_id="sc01",
        title="Entry",
        script_beat="Kai enters.",
        duration_s=6,
        status=ShotStatus.draft,
        prompt_sections=_prompt(),
        refs=[ShotRef(role=RefRole.actor, asset_id="act_kai", picture_index=1)],
    )
    save_shot(shot)
    save_project(project.model_copy(update={"shot_ids": [shot.id]}))

    payloads: list[dict] = []
    notes, _ = await _run_tools(
        project_id=project.id,
        tools=[{"name": "review_sequence", "args": {}}],
        svc=object(),
        actions=[],
        result_payloads=payloads,
    )
    assert payloads[0]["ok"] is True
    assert payloads[0]["sequence"]["shot_count"] == 1
    assert any("0:06" in line for line in notes)
