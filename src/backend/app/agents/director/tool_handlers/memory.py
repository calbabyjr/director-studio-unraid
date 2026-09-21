"""Standing-note tools so Director can remember across sessions."""

from __future__ import annotations

from typing import Any

from ....core.projects.director_memory import add_note, forget_note, load_notes
from ....core.souls.store import default_soul_id, get_soul, record_soul_lesson
from ....core.projects.store import load_project

_MEMORY_TOOLS = frozenset({"remember_note", "forget_note", "improve_soul"})


async def handle_memory_tool(
    *,
    name: str,
    args: dict[str, Any],
    project_id: str,
    actions: list[str],
    notes: list[str],
    result_payloads: list[dict[str, Any]] | None,
) -> bool:
    if name not in _MEMORY_TOOLS:
        return False

    if name == "improve_soul":
        text = str(args.get("text") or "").strip()
        if not text:
            notes.append("improve_soul: missing text")
            return True
        project = load_project(project_id)
        soul_id = (getattr(project, "soul_id", None) or default_soul_id()) if project else default_soul_id()
        lesson = record_soul_lesson(soul_id, text, source="director")
        if lesson is None:
            notes.append("improve_soul: active soul is missing")
            return True
        soul = get_soul(soul_id)
        actions.append(f"improve_soul:{lesson.id}")
        notes.append(
            f"Learned on soul {(soul.name if soul else soul_id)}: {lesson.text}"
        )
        if result_payloads is not None:
            result_payloads.append({"ok": True, "lesson": lesson.model_dump(mode="json")})
        return True

    if name == "remember_note":
        text = str(args.get("text") or "").strip()
        scope = str(args.get("scope") or "project").strip().lower()
        if scope not in {"project", "global"}:
            scope = "project"
        if not text:
            notes.append("remember_note: missing text")
            return True
        saved = add_note(
            text=text,
            scope=scope,  # type: ignore[arg-type]
            source="director",
            project_id=project_id,
        )
        from ....core.souls.store import soul_worthy_lesson

        if soul_worthy_lesson(saved.text):
            project = load_project(project_id)
            soul_id = (getattr(project, "soul_id", None) or default_soul_id()) if project else default_soul_id()
            record_soul_lesson(soul_id, saved.text, source="director")
        actions.append(f"remember_note:{saved.id}")
        label = "all projects" if saved.scope == "global" else "this project"
        notes.append(f"Remembered for {label}: {saved.text}")
        if result_payloads is not None:
            result_payloads.append({"ok": True, "note": saved.model_dump(mode="json")})
        return True

    token = str(args.get("note_id") or args.get("text") or "").strip()
    removed = forget_note(token, project_id=project_id) if token else None
    if removed is None:
        known = ", ".join(note.id for note in load_notes(project_id)[-8:]) or "none"
        notes.append(f"forget_note: no matching standing note. Known ids: {known}")
        return True
    actions.append(f"forget_note:{removed.id}")
    notes.append(f"Forgot standing note: {removed.text}")
    if result_payloads is not None:
        result_payloads.append({"ok": True, "removed": removed.model_dump(mode="json")})
    return True
