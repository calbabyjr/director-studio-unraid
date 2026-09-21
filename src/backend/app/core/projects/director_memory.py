"""Durable Director standing notes that survive chat clipping and new sessions."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ...config import settings
from ..paths import ensure_project_tree

MAX_NOTES_PER_SCOPE = 24
MAX_NOTE_CHARS = 240
MAX_PROMPT_CHARS = 1800
Scope = Literal["project", "global"]
Source = Literal["user", "director", "auto"]


class DirectorMemoryNote(BaseModel):
    id: str
    text: str
    scope: Scope = "project"
    source: Source = "user"
    created_at: str
    updated_at: str


class DirectorMemory(BaseModel):
    notes: list[DirectorMemoryNote] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"mem_{uuid.uuid4().hex[:12]}"


def project_memory_path(project_id: str) -> Path:
    ensure_project_tree(project_id)
    return settings.projects_dir / project_id / "agent" / "memory.json"


def global_memory_path() -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir / "director_memory.json"


def _load(path: Path) -> DirectorMemory:
    if not path.is_file():
        return DirectorMemory()
    try:
        return DirectorMemory.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return DirectorMemory()


def _save(path: Path, memory: DirectorMemory) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(memory.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).strip(" \"'`.,;:")


def _clip(text: str) -> str:
    cleaned = _normalize(text)
    if len(cleaned) <= MAX_NOTE_CHARS:
        return cleaned
    return cleaned[: MAX_NOTE_CHARS - 1].rstrip() + "…"


def _path_for_scope(project_id: str | None, scope: Scope) -> Path:
    if scope == "global":
        return global_memory_path()
    if not project_id:
        raise ValueError("project_id is required for project memory")
    return project_memory_path(project_id)


def load_notes(project_id: str | None = None) -> list[DirectorMemoryNote]:
    if project_id:
        _bootstrap_from_history(project_id)
    notes = list(_load(global_memory_path()).notes)
    if project_id:
        notes.extend(_load(project_memory_path(project_id)).notes)
    return notes


def _deduped(existing: list[DirectorMemoryNote], text: str) -> DirectorMemoryNote | None:
    needle = _normalize(text).lower()
    if not needle:
        return None
    for note in existing:
        hay = _normalize(note.text).lower()
        if hay == needle or needle in hay or hay in needle:
            return note
    return None


def add_note(
    *,
    text: str,
    scope: Scope = "project",
    source: Source = "user",
    project_id: str | None = None,
) -> DirectorMemoryNote:
    clipped = _clip(text)
    if len(clipped) < 8:
        raise ValueError("memory note is too short")
    path = _path_for_scope(project_id, scope)
    memory = _load(path)
    duplicate = _deduped(memory.notes, clipped)
    if duplicate is not None:
        return duplicate
    while len(memory.notes) >= MAX_NOTES_PER_SCOPE:
        auto_idx = next(
            (index for index, note in enumerate(memory.notes) if note.source == "auto"),
            0,
        )
        memory.notes.pop(auto_idx)
    now = _now()
    note = DirectorMemoryNote(
        id=_new_id(),
        text=clipped,
        scope=scope,
        source=source,
        created_at=now,
        updated_at=now,
    )
    memory.notes.append(note)
    _save(path, memory)
    return note


def forget_note(note_id: str, *, project_id: str | None = None) -> DirectorMemoryNote | None:
    token = (note_id or "").strip()
    if not token:
        return None
    paths = [global_memory_path()]
    if project_id:
        paths.insert(0, project_memory_path(project_id))
    needle = _normalize(token).lower()
    for path in paths:
        memory = _load(path)
        kept: list[DirectorMemoryNote] = []
        removed: DirectorMemoryNote | None = None
        for note in memory.notes:
            if removed is None and (
                note.id == token or needle in _normalize(note.text).lower()
            ):
                removed = note
                continue
            kept.append(note)
        if removed is not None:
            _save(path, DirectorMemory(notes=kept))
            return removed
    return None


def memory_prompt_block(project_id: str) -> str:
    notes = load_notes(project_id)
    if not notes:
        return ""
    lines = [
        "STANDING_NOTES (persist across sessions; follow unless the user overrides this turn):"
    ]
    used = 0
    for note in notes:
        label = "all projects" if note.scope == "global" else "this project"
        line = f"- [{label}] {note.text}"
        if used + len(line) + 1 > MAX_PROMPT_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def apply_memory_to_system(system: str, project_id: str) -> str:
    block = memory_prompt_block(project_id)
    if not block:
        return system
    return f"{system.rstrip()}\n\n{block}"


_SKIP_MESSAGE = re.compile(
    r"^(retry|ok|okay|yes|no|y|n|a|b|c|1|2|3)\s*[.!]*\s*$",
    re.I,
)
_EXPLICIT_REMEMBER = re.compile(
    r"(?:please\s+)?remember(?:\s+that|\s+this)?[:\s]+(.{8,240})",
    re.I,
)
_FROM_NOW_ON = re.compile(
    r"(?:from now on|going forward)[,:\s]+(.{8,240})",
    re.I,
)
_PRODUCTION_WIDE = re.compile(
    r"([^.!?\n]{8,220}\b(?:this production|this film|this storyboard|"
    r"this project(?!\s+library)|the production|the film)\b[^.!?\n]{0,160})",
    re.I,
)
_NOT_BUT = re.compile(
    r"((?:it|this|that)\s+(?:is not|isn'?t|is no longer)\s+[^.!?\n]{3,80}"
    r"(?:[.!,]|\s+)(?:it\s+is|it'?s|this\s+is)\s+[^.!?\n]{3,80})",
    re.I,
)
_THIS_IS_NOT = re.compile(
    r"((?:this is|it is|it'?s)\s+(?:a\s+)?[\w][\w\s-]{1,40},\s*not\s+(?:a\s+)?[\w][\w\s-]{1,40})",
    re.I,
)
_ALWAYS_NEVER = re.compile(
    r"(?:^|[.!?]\s+)((?:always|never|do not|don't)\s+[^.!?\n]{10,200})",
    re.I,
)
_ROLE_FACT = re.compile(
    r"\b([A-Z][\w'-]{1,24}\s+is the\s+(?:dom(?:inant|inatrix)?|submissive|sub|lead)"
    r"(?:\s*,\s*not\s+[A-Z][\w'-]{1,24})?)",
)
_EPHEMERAL = re.compile(
    r"\b(yet|this turn|this message|retry|batch|unrequested|optional layout)\b",
    re.I,
)
_DURABLE_CONSTRAINT = re.compile(
    r"\b(actor|actors|warehouse|dungeon|costume|wardrobe|create|invent|"
    r"text prompt|this production|this film|this project)\b",
    re.I,
)


def extract_memory_candidates(message: str) -> list[str]:
    text = (message or "").strip()
    if not text or _SKIP_MESSAGE.match(text):
        return []
    if "Saved reference delta" in text or "Use the saved delta" in text:
        return []
    if text.endswith("?") and len(text) < 90:
        return []
    found: list[str] = []
    for pattern in (
        _EXPLICIT_REMEMBER,
        _FROM_NOW_ON,
        _PRODUCTION_WIDE,
        _NOT_BUT,
        _THIS_IS_NOT,
        _ALWAYS_NEVER,
        _ROLE_FACT,
    ):
        for match in pattern.finditer(text):
            candidate = _clip(re.sub(r"^(?:to|that|this)\s+", "", match.group(1), flags=re.I))
            if len(candidate) < 8:
                continue
            if pattern is _ALWAYS_NEVER and (
                _EPHEMERAL.search(candidate) or not _DURABLE_CONSTRAINT.search(candidate)
            ):
                continue
            found.append(candidate)
    unique: list[str] = []
    seen: set[str] = set()
    for item in found:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _bootstrap_from_history(project_id: str) -> None:
    path = project_memory_path(project_id)
    if path.exists():
        return
    from .chat_history import load_chat_history

    added = False
    for message in load_chat_history(project_id):
        if message.role != "user":
            continue
        for candidate in extract_memory_candidates(message.content):
            add_note(
                text=candidate,
                scope="project",
                source="auto",
                project_id=project_id,
            )
            added = True
    if not added:
        _save(path, DirectorMemory())


def capture_user_memory(project_id: str, message: str) -> list[DirectorMemoryNote]:
    """Persist durable facts from this user turn and, once, from older chat."""
    _bootstrap_from_history(project_id)
    captured: list[DirectorMemoryNote] = []
    for candidate in extract_memory_candidates(message):
        captured.append(
            add_note(
                text=candidate,
                scope="project",
                source="auto",
                project_id=project_id,
            )
        )
    if captured:
        try:
            from ..souls.store import record_soul_lesson, soul_worthy_lesson
            from .store import load_project

            project = load_project(project_id)
            soul_id = (getattr(project, "soul_id", None) or "studio") if project else "studio"
            for note in captured:
                if soul_worthy_lesson(note.text):
                    record_soul_lesson(soul_id, note.text, source="auto")
        except Exception:
            pass
    return captured
