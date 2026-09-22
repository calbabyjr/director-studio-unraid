"""Request-scoped project id so workspace files can load with the Director skill."""

from __future__ import annotations

from contextvars import ContextVar, Token

_active_project_id: ContextVar[str | None] = ContextVar(
    "director_workspace_project_id", default=None
)


def bind_workspace_project(project_id: str | None) -> Token:
    return _active_project_id.set((project_id or "").strip() or None)


def active_workspace_project_id() -> str | None:
    return _active_project_id.get()
