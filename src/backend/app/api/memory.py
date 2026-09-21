"""Director standing notes that persist across chat sessions."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.projects.director_memory import (
    DirectorMemoryNote,
    add_note,
    forget_note,
    load_notes,
)
from ..core.projects.store import load_project

router = APIRouter(tags=["director-memory"])


class MemoryListResponse(BaseModel):
    notes: list[DirectorMemoryNote]


class AddMemoryBody(BaseModel):
    text: str = Field(..., min_length=8, max_length=240)
    scope: str = Field(default="project")


@router.get("/projects/{project_id}/memory", response_model=MemoryListResponse)
async def list_project_memory(project_id: str) -> MemoryListResponse:
    if load_project(project_id) is None:
        raise HTTPException(404, "Project not found")
    return MemoryListResponse(notes=load_notes(project_id))


@router.post("/projects/{project_id}/memory", response_model=DirectorMemoryNote)
async def add_project_memory(project_id: str, body: AddMemoryBody) -> DirectorMemoryNote:
    if load_project(project_id) is None:
        raise HTTPException(404, "Project not found")
    scope = body.scope.strip().lower()
    if scope not in {"project", "global"}:
        raise HTTPException(400, "scope must be project or global")
    try:
        return add_note(
            text=body.text,
            scope=scope,  # type: ignore[arg-type]
            source="user",
            project_id=project_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/projects/{project_id}/memory/{note_id}", response_model=DirectorMemoryNote)
async def delete_project_memory(project_id: str, note_id: str) -> DirectorMemoryNote:
    if load_project(project_id) is None:
        raise HTTPException(404, "Project not found")
    removed = forget_note(note_id, project_id=project_id)
    if removed is None:
        raise HTTPException(404, "Standing note not found")
    return removed
