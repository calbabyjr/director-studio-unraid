from __future__ import annotations

import asyncio

from app.core.projects.choice_questions import normalize_choice_questions
from app.agents.director.screenplay_interview import (
    ScreenplayInterview,
    _parse_interview_reply,
    _parse_script,
    _wants_pages,
    load_interview,
    run_interview_turn,
    save_interview,
)
from app.core.projects.store import create_project, load_project


def test_normalize_choice_questions_from_flat_payload():
    questions = normalize_choice_questions(
        {"question": "Tone?", "options": ["tender", "intense", "tender"], "allow_multiple": True}
    )
    assert len(questions) == 1
    assert questions[0].prompt == "Tone?"
    assert questions[0].options == ["tender", "intense"]


def test_parse_interview_reply_and_script():
    question, ready, brief, choices = _parse_interview_reply(
        '{"question":"Who is the lead?","ready":false,"brief":"","questions":[{"prompt":"Who is the lead?","options":["Jenny","Wendy"],"allow_multiple":true}]}'
    )
    assert question == "Who is the lead?"
    assert ready is False
    assert [item.prompt for item in choices] == ["Who is the lead?"]
    assert choices[0].options == ["Jenny", "Wendy"]
    script = _parse_script('{"script":"INT. DUNGEON - NIGHT\\n\\nJENNY waits."}')
    assert script.startswith("INT. DUNGEON")
    assert _wants_pages("write the screenplay now")
    assert not _wants_pages("she is tired")


def test_interview_stores_premise_and_question(tmp_projects_dir, monkeypatch):
    from app.agents.director import screenplay_interview as module

    project = create_project("Interview film", "")

    async def fake_complete(system, user, *, guides=()):
        return '{"question":"What does she want tonight?","ready":false,"brief":""}'

    monkeypatch.setattr(module, "_complete", fake_complete)
    result = asyncio.run(run_interview_turn(project.id, "Two women in a dungeon."))
    assert result["premise"].startswith("Two women")
    assert result["turns"][0]["role"] == "user"
    assert result["turns"][1]["content"] == "What does she want tonight?"
    assert result["ready"] is False
    assert result["drafted"] is False
    saved = load_interview(project.id)
    assert saved.premise.startswith("Two women")


def test_interview_generate_saves_unlocked_draft(tmp_projects_dir, monkeypatch):
    from app.agents.director import screenplay_interview as module

    project = create_project("Interview film", "")
    save_interview(
        project.id,
        ScreenplayInterview(
            premise="Jenny and Wendy in a dungeon.",
            turns=[],
            ready=True,
            brief="A short dungeon scene.",
        ),
    )

    async def fake_complete(system, user, *, guides=()):
        return '{"script":"INT. DUNGEON - NIGHT\\n\\nJENNY\\nStay."}'

    monkeypatch.setattr(module, "_complete", fake_complete)
    result = asyncio.run(run_interview_turn(project.id, "", generate=True))
    assert result["drafted"] is True
    assert "INT. DUNGEON" in result["script_text"]
    saved = load_project(project.id)
    assert saved.script_draft_pending is True
    assert saved.script_locked is False
    assert saved.script_text.startswith("INT. DUNGEON")


def test_interview_reset_clears_state(tmp_projects_dir):
    project = create_project("Interview film", "")
    save_interview(project.id, ScreenplayInterview(premise="old idea", ready=True))
    result = asyncio.run(run_interview_turn(project.id, "", reset=True))
    assert result["premise"] == ""
    assert result["turns"] == []
    assert load_interview(project.id).premise == ""
