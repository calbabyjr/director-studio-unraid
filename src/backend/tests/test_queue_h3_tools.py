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


def test_parse_prompt_sections_coerces_list_subject_and_inventory_fallback():
    from types import SimpleNamespace
    from app.agents.director.planner import prompt_section_inventory_fallback

    parsed = parse_prompt_sections_json(
        '{"subjectDefinitions": ["Jenny in <Picture 2>."], "summary": "Hold.", '
        '"retention_analysis": "Keep set.", "detailed_description": "0-4 seconds: wait.", '
        '"overall_soundscape": "Room tone.", "non_diegetic_music": "None."}'
    )
    assert "Jenny" in parsed["subject_definitions"]
    assert "<Picture 2>" in parsed["subject_definitions"]

    shot = SimpleNamespace(
        title="Establish the Space",
        script_beat="Jenny at the edge of frame.",
        duration_s=4,
        source_audio_path="",
        refs=[
            SimpleNamespace(role=SimpleNamespace(value="scene"), picture_index=1),
            SimpleNamespace(role=SimpleNamespace(value="actor"), picture_index=2),
        ],
        voice_refs=[],
    )
    filled = prompt_section_inventory_fallback(shot)
    assert "<Picture 1>" in filled["subject_definitions"]
    assert "<Picture 2>" in filled["subject_definitions"]
    assert filled["summary"].startswith("Jenny")
    parsed_empty = parse_prompt_sections_json("{}", fallback=filled)
    assert parsed_empty["subject_definitions"] == filled["subject_definitions"]


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
