from app.agents.director.intent import explicit_h3_generation_intent
from app.agents.director.planner import parse_prompt_sections_json
from app.agents.director.tool_schema import director_tool_schemas, offered_tool_names
from app.core.projects.store import create_project


def test_parse_prompt_sections_fills_from_fallback_and_aliases():
    raw = '{"summary": "A locked-off dungeon hold.", "description": "0-4 seconds: Jenny waits."}'
    parsed = parse_prompt_sections_json(
        raw,
        fallback={
            "subject_definitions": "Jenny from <Picture 1>.",
            "retention_analysis": "Keep the dungeon.",
            "detailed_description": "",
            "overall_soundscape": "Room tone.",
            "non_diegetic_music": "Low drone.",
        },
    )
    assert parsed["subject_definitions"].startswith("Jenny")
    assert "dungeon" in parsed["summary"]
    assert parsed["detailed_description"].startswith("0-4")


def test_move_to_generating_h3_offers_only_queue_h3(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = create_project("H3 film", "Jenny walks.")
    assert explicit_h3_generation_intent("move to generating H3")
    names = offered_tool_names(
        director_tool_schemas(project, current_message="move to generating H3")
    )
    assert names == frozenset({"queue_h3", "get_status"})
