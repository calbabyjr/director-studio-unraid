from app.core.h3.prompt import merge_user_locked_prompt, stamp_user_prompt_lock, user_locked_prompt_dict
from app.core.projects.models import PromptSections, Shot, ShotStatus


def _shot(**meta):
    return Shot(
        id="sht_lock",
        project_id="prj_lock",
        scene_id="sc01",
        title="Establish the Space",
        script_beat="Jenny waits.",
        duration_s=4.0,
        status=ShotStatus.needs_review,
        meta=dict(meta),
    )


def test_stamp_and_read_user_prompt_lock():
    sections = PromptSections(
        subject_definitions="Jenny from Picture 1, nude, collar.",
        summary="Locked-off dungeon establish.",
        retention_analysis="Keep Jenny small at frame left.",
        detailed_description="0–4 seconds: she holds.",
        overall_soundscape="Room tone.",
        non_diegetic_music="Drone.",
    )
    shot = _shot()
    meta = stamp_user_prompt_lock(shot, sections)
    locked_shot = shot.model_copy(update={"meta": meta, "prompt_sections": sections})
    locked = user_locked_prompt_dict(locked_shot)
    assert locked is not None
    assert locked["summary"] == "Locked-off dungeon establish."
    assert meta["prompt_user_edited"] is True


def test_merge_keeps_user_wording_and_grafts_missing_picture_tags():
    generated = PromptSections(
        subject_definitions="S1 is the lead in <Picture 1>. <Picture 2> is the dungeon.",
        summary="A short cafe walk-in.",
        retention_analysis="Retain the actor.",
        detailed_description="Actor enters.",
        overall_soundscape="Cafe.",
        non_diegetic_music="Piano.",
    )
    locked = {
        "subject_definitions": "Jenny nude at the left edge, collar and leash only.",
        "summary": "My locked-off red dungeon establish.",
        "retention_analysis": "Keep her small.",
        "detailed_description": "0–4 seconds: one slow step.",
        "overall_soundscape": "Concrete hum.",
        "non_diegetic_music": "Cello drone.",
    }
    merged = merge_user_locked_prompt(generated, locked)
    assert merged.summary == "My locked-off red dungeon establish."
    assert "Jenny nude at the left edge" in merged.subject_definitions
    assert "<Picture 1>" in merged.subject_definitions
    assert "<Picture 2>" in merged.subject_definitions
    assert "cafe" not in merged.summary.lower()
