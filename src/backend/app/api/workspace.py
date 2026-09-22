"""Director workspace files: user.md plus additional markdown the Director loads."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.workspace.store import (
    WorkspaceFile,
    delete_file,
    get_file,
    list_files,
    save_file,
)

router = APIRouter(tags=["director-workspace"])

Scope = Literal["global", "project"]


class WorkspaceFileResponse(BaseModel):
    name: str
    scope: Scope
    markdown: str
    reserved: bool
    placeholder: bool
    updated_at: str


class CreateWorkspaceBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    markdown: str = ""
    scope: Scope = "global"
    project_id: str | None = None
    soul_id: str | None = None


class UpdateWorkspaceBody(BaseModel):
    markdown: str
    scope: Scope = "global"
    project_id: str | None = None
    soul_id: str | None = None


def _to_response(item: WorkspaceFile) -> WorkspaceFileResponse:
    return WorkspaceFileResponse.model_validate(item.model_dump())


def _require_project(scope: Scope, project_id: str | None) -> str | None:
    if scope != "project":
        return None
    slug = (project_id or "").strip()
    if not slug:
        raise HTTPException(400, "project_id is required for project workspace files")
    return slug


@router.get("/workspace", response_model=list[WorkspaceFileResponse])
async def list_workspace_files(
    scope: Scope = Query("global"),
    project_id: str | None = Query(None),
    soul_id: str | None = Query(None),
) -> list[WorkspaceFileResponse]:
    pid = _require_project(scope, project_id)
    try:
        return [_to_response(item) for item in list_files(scope, pid, soul_id)]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/workspace", response_model=WorkspaceFileResponse)
async def create_workspace_file(body: CreateWorkspaceBody) -> WorkspaceFileResponse:
    pid = _require_project(body.scope, body.project_id)
    try:
        return _to_response(
            save_file(
                body.name,
                body.markdown,
                scope=body.scope,
                project_id=pid,
                soul_id=body.soul_id,
                create=True,
            )
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/workspace/{name:path}", response_model=WorkspaceFileResponse)
async def get_workspace_file(
    name: str,
    scope: Scope = Query("global"),
    project_id: str | None = Query(None),
    soul_id: str | None = Query(None),
) -> WorkspaceFileResponse:
    pid = _require_project(scope, project_id)
    try:
        item = get_file(name, scope, pid, soul_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if item is None:
        raise HTTPException(404, "Workspace file not found")
    return _to_response(item)


@router.put("/workspace/{name:path}", response_model=WorkspaceFileResponse)
async def update_workspace_file(name: str, body: UpdateWorkspaceBody) -> WorkspaceFileResponse:
    pid = _require_project(body.scope, body.project_id)
    try:
        return _to_response(
            save_file(
                name,
                body.markdown,
                scope=body.scope,
                project_id=pid,
                soul_id=body.soul_id,
            )
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 400
        raise HTTPException(status, str(exc)) from exc


@router.delete("/workspace/{name:path}")
async def delete_workspace_file(
    name: str,
    scope: Scope = Query("global"),
    project_id: str | None = Query(None),
    soul_id: str | None = Query(None),
) -> dict:
    pid = _require_project(scope, project_id)
    try:
        delete_file(name, scope, pid, soul_id)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            status = 404
        elif "cannot delete" in message:
            status = 400
        else:
            status = 400
        raise HTTPException(status, message) from exc
    return {"ok": True, "name": name}
