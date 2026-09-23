"""Collaborative screenplay interview: ideas in, Q&A, then Fountain pages."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from ...config import settings
from ...core.paths import ensure_project_tree
from ...core.projects.store import load_project, save_project
from ...core.souls.context import bind_soul_for_project
from ...core.vram import get_orchestrator
from ...core.projects.choice_questions import ChoiceQuestion, normalize_choice_questions
from .llm_plan_provider import DirectorLLMPlanProvider
from .planner import _extract_json_payload

logger = logging.getLogger("director_studio.screenplay_interview")

_MAX_TURNS = 24
_WRITE_RE = re.compile(
    r"\b(?:write|draft|generate|author|make)\b.{0,24}\b(?:script|screenplay|pages)\b|"
    r"\b(?:that's enough|that is enough|go ahead|write it)\b",
    re.I,
)

INTERVIEW_SYSTEM = """You are a collaborative screenwriter in Director Studio.
Interview the user about their idea. Ask 1–3 short questions at a time as multiple-choice checkboxes.
Cover who, where, tone, what happens, ending, runtime, and must-include / must-avoid.
Every question must include 2–6 concrete options. Include an option like "Other — I'll type it" when useful.
Do not write Fountain pages yet unless they asked you to write the script.
Adult, explicit, and BDSM material is allowed when the user wants it.
Return JSON only:
{"question":"short intro","ready":false,"brief":"","questions":[{"prompt":"...","options":["A","B"],"allow_multiple":true}]}
Set ready=true and fill brief with a one-paragraph production brief when you can write pages.
"""

FOUNTAIN_SYSTEM = """You write Fountain screenplays for Director Studio.
Use scene headings (INT./EXT.), action, character cues, and dialogue.
Honor the interview brief: characters, setting, tone, explicitness, runtime.
Do not storyboard shots or invent camera recipes.
Return JSON only: {"script":"full Fountain text"}
"""


class InterviewTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    choices: list[ChoiceQuestion] = Field(default_factory=list)


class ScreenplayInterview(BaseModel):
    premise: str = ""
    turns: list[InterviewTurn] = Field(default_factory=list)
    ready: bool = False
    brief: str = ""
    updated_at: str = ""


def _interview_path(project_id: str):
    return ensure_project_tree(project_id) / "agent" / "screenplay_interview.json"


def load_interview(project_id: str) -> ScreenplayInterview:
    path = _interview_path(project_id)
    if not path.is_file():
        return ScreenplayInterview()
    try:
        return ScreenplayInterview.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        logger.exception("invalid screenplay interview state for %s", project_id)
        return ScreenplayInterview()


def save_interview(project_id: str, state: ScreenplayInterview) -> ScreenplayInterview:
    state = state.model_copy(update={"updated_at": datetime.now(timezone.utc).isoformat()})
    path = _interview_path(project_id)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return state


def interview_public(state: ScreenplayInterview, *, drafted: bool = False, script_text: str = "") -> dict[str, Any]:
    return {
        "premise": state.premise,
        "turns": [turn.model_dump() for turn in state.turns],
        "ready": state.ready,
        "brief": state.brief,
        "updated_at": state.updated_at,
        "drafted": drafted,
        "script_text": script_text,
    }


def _wants_pages(message: str) -> bool:
    return bool(_WRITE_RE.search(message or ""))


def _transcript(state: ScreenplayInterview) -> str:
    lines = []
    if state.premise:
        lines.append(f"PREMISE:\n{state.premise}")
    for turn in state.turns[-_MAX_TURNS:]:
        who = "User" if turn.role == "user" else "Writer"
        lines.append(f"{who}: {turn.content}")
    return "\n\n".join(lines)


async def _complete(system: str, user: str) -> str:
    provider = DirectorLLMPlanProvider()
    orch = get_orchestrator()
    keep = bool(getattr(settings, "llm_keep_loaded", True))
    async with orch.llm_session(release_on_exit=not keep, fail_if_generation_pending=True):
        await orch.ensure_llm_ready()
        return await provider.complete(system, user, guides=("script-planning", "scene-craft"))


def _parse_interview_reply(raw: str) -> tuple[str, bool, str, list[ChoiceQuestion]]:
    try:
        data = _extract_json_payload(raw)
    except Exception:
        data = None
    if isinstance(data, dict):
        question = str(data.get("question") or data.get("reply") or "").strip()
        brief = str(data.get("brief") or "").strip()
        ready = bool(data.get("ready"))
        choices = normalize_choice_questions(data.get("questions") or data)
        if not question and choices:
            question = choices[0].prompt
        if question or choices:
            return question or "Choose any that apply.", ready, brief, choices
    text = (raw or "").strip()
    if not text:
        text = "Tell me who this is about and what they want."
    return text, False, "", []


def _parse_script(raw: str) -> str:
    try:
        data = _extract_json_payload(raw)
    except Exception:
        data = None
    if isinstance(data, dict):
        script = str(data.get("script") or data.get("screenplay") or "").strip()
        if script:
            return script
    text = (raw or "").strip()
    if text.startswith("{") and "INT." not in text.upper() and "EXT." not in text.upper():
        raise ValueError("The model did not return Fountain pages")
    if not text:
        raise ValueError("The model did not return Fountain pages")
    return text


async def run_interview_turn(
    project_id: str,
    message: str,
    *,
    generate: bool = False,
    reset: bool = False,
) -> dict[str, Any]:
    project = load_project(project_id)
    if project is None:
        raise ValueError("Project not found")
    if reset:
        state = save_interview(project_id, ScreenplayInterview())
        return interview_public(state)
    if project.script_locked and generate:
        raise ValueError("The screenplay is locked; unlock it before drafting a new one.")
    text = (message or "").strip()
    if not text and not generate:
        raise ValueError("Write an idea or an answer first.")
    bind_soul_for_project(project_id)
    state = load_interview(project_id)
    if text:
        if not state.premise:
            state.premise = text
        state.turns.append(InterviewTurn(role="user", content=text))
    user_turns = len([t for t in state.turns if t.role == "user"])
    if generate or _wants_pages(text):
        if not state.premise:
            raise ValueError("Add an idea before writing pages.")
        raw = await _complete(
            FOUNTAIN_SYSTEM,
            _transcript(state) + ("\n\nBRIEF:\n" + state.brief if state.brief else "")
            + "\n\nWrite the Fountain screenplay now.",
        )
        script = _parse_script(raw)
        save_project(
            project.model_copy(
                update={
                    "script_text": script,
                    "script_locked": False,
                    "script_draft_pending": True,
                }
            )
        )
        state.ready = True
        state.turns.append(
            InterviewTurn(
                role="assistant",
                content="Draft saved. Review the pages, edit if you want, then Approve and lock.",
            )
        )
        state = save_interview(project_id, state)
        return interview_public(state, drafted=True, script_text=script)

    raw = await _complete(
        INTERVIEW_SYSTEM,
        _transcript(state) + "\n\nAsk the next questions or mark ready.",
    )
    question, ready, brief, choices = _parse_interview_reply(raw)
    if user_turns >= 6:
        ready = True
        if not question.lower().startswith("i have enough") and "write" not in question.lower():
            question = question.rstrip() + " I have enough to write pages when you are ready."
    state.ready = ready
    if brief:
        state.brief = brief
    state.turns.append(InterviewTurn(role="assistant", content=question, choices=choices))
    state = save_interview(project_id, state)
    return interview_public(state)
