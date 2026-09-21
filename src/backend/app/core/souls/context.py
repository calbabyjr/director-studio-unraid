from __future__ import annotations

from contextvars import ContextVar, Token

_active_soul_id: ContextVar[str | None] = ContextVar("director_soul_id", default=None)


def bind_soul(soul_id: str | None) -> Token:
    return _active_soul_id.set((soul_id or "").strip() or None)


def active_soul_id() -> str | None:
    return _active_soul_id.get()


def bind_soul_for_project(project_id: str | None) -> Token:
    from ..projects.store import load_project
    from .store import default_soul_id

    soul_id = default_soul_id()
    if project_id:
        project = load_project(project_id)
        if project is not None and getattr(project, "soul_id", None):
            soul_id = project.soul_id
    return bind_soul(soul_id)
