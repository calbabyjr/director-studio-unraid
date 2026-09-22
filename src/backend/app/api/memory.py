"""Director standing notes and compiled permanent MEMORY.md."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.projects.director_learning import (
    MAX_MEMORY_MD_CHARS,
    read_memory_md,
    write_memory_md,
)
from ..core.projects.director_memory import (
    DirectorMemoryNote,
    add_note,
    forget_note,
    load_notes,
)
from ..core.projects.store import load_project

router = APIRouter(tags=["director-memory"])

Scope = Literal["global", "project"]


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


class MemoryDocumentResponse(BaseModel):
    scope: Scope
    markdown: str
    placeholder: bool
    soul_id: str | None = None
    updated_at: str | None = None


class UpdateMemoryDocumentBody(BaseModel):
    markdown: str = Field(..., max_length=MAX_MEMORY_MD_CHARS)
    scope: Scope = "global"
    project_id: str | None = None
    soul_id: str | None = None


def _document_response(
    scope: Scope,
    project_id: str | None,
    soul_id: str | None = None,
) -> MemoryDocumentResponse:
    from ..core.projects.director_learning import memory_md_is_placeholder, memory_md_path
    from ..core.souls.store import resolve_soul_id

    slug = resolve_soul_id(soul_id, project_id) if scope == "global" else None
    markdown = read_memory_md(scope, project_id, soul_id)
    path = memory_md_path(scope, project_id, soul_id)
    updated = None
    if path.is_file():
        from datetime import datetime, timezone

        updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return MemoryDocumentResponse(
        scope=scope,
        markdown=markdown,
        placeholder=memory_md_is_placeholder(markdown),
        soul_id=slug,
        updated_at=updated,
    )


@router.get("/memory/document", response_model=MemoryDocumentResponse)
async def get_memory_document(
    scope: Scope = Query("global"),
    project_id: str | None = Query(None),
    soul_id: str | None = Query(None),
) -> MemoryDocumentResponse:
    if scope == "project":
        slug = (project_id or "").strip()
        if not slug:
            raise HTTPException(400, "project_id is required for project memory")
        if load_project(slug) is None:
            raise HTTPException(404, "Project not found")
        project_id = slug
    else:
        project_id = None
    return _document_response(scope, project_id, soul_id)


@router.put("/memory/document", response_model=MemoryDocumentResponse)
async def update_memory_document(body: UpdateMemoryDocumentBody) -> MemoryDocumentResponse:
    project_id = None
    if body.scope == "project":
        slug = (body.project_id or "").strip()
        if not slug:
            raise HTTPException(400, "project_id is required for project memory")
        if load_project(slug) is None:
            raise HTTPException(404, "Project not found")
        project_id = slug
    try:
        write_memory_md(body.markdown, body.scope, project_id, body.soul_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _document_response(body.scope, project_id, body.soul_id)
