"""Director soul CRUD: editable soul.md plus learned lessons."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.souls.store import (
    DirectorSoul,
    create_soul,
    delete_soul,
    get_soul,
    lessons_markdown,
    list_souls,
    record_soul_lesson,
    save_soul,
)

router = APIRouter(tags=["director-souls"])


class CreateSoulBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = ""
    markdown: str = ""


class UpdateSoulBody(BaseModel):
    name: str | None = None
    description: str | None = None
    markdown: str | None = None
    lessons: str | None = Field(
        default=None,
        description="Optional full replacement of lessons.md as bullet lines.",
    )


class AddLessonBody(BaseModel):
    text: str = Field(..., min_length=8, max_length=240)


class SoulResponse(BaseModel):
    id: str
    name: str
    description: str
    builtin: bool
    markdown: str
    lessons: str
    updated_at: str


def _to_response(soul: DirectorSoul) -> SoulResponse:
    return SoulResponse(
        id=soul.id,
        name=soul.name,
        description=soul.description,
        builtin=soul.builtin,
        markdown=soul.markdown,
        lessons=lessons_markdown(soul),
        updated_at=soul.updated_at,
    )


@router.get("/souls", response_model=list[SoulResponse])
async def list_director_souls() -> list[SoulResponse]:
    return [_to_response(soul) for soul in list_souls()]


@router.post("/souls", response_model=SoulResponse)
async def create_director_soul(body: CreateSoulBody) -> SoulResponse:
    try:
        return _to_response(
            create_soul(name=body.name, markdown=body.markdown, description=body.description)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/souls/{soul_id}", response_model=SoulResponse)
async def get_director_soul(soul_id: str) -> SoulResponse:
    soul = get_soul(soul_id)
    if soul is None:
        raise HTTPException(404, "Soul not found")
    return _to_response(soul)


@router.put("/souls/{soul_id}", response_model=SoulResponse)
async def update_director_soul(soul_id: str, body: UpdateSoulBody) -> SoulResponse:
    try:
        return _to_response(
            save_soul(
                soul_id,
                markdown=body.markdown,
                name=body.name,
                description=body.description,
                lessons_markdown=body.lessons,
            )
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 400
        raise HTTPException(status, str(exc)) from exc


@router.post("/souls/{soul_id}/lessons", response_model=SoulResponse)
async def add_director_soul_lesson(soul_id: str, body: AddLessonBody) -> SoulResponse:
    if get_soul(soul_id) is None:
        raise HTTPException(404, "Soul not found")
    record_soul_lesson(soul_id, body.text, source="user")
    soul = get_soul(soul_id)
    assert soul is not None
    return _to_response(soul)


@router.delete("/souls/{soul_id}")
async def delete_director_soul(soul_id: str) -> dict:
    try:
        delete_soul(soul_id)
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 400
        raise HTTPException(status, str(exc)) from exc
    return {"ok": True, "id": soul_id}
