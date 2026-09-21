"""User-editable Director souls: persona markdown plus learned lessons."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ...config import settings
from .templates import BUILTIN_SOULS

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.DOTALL)
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
MAX_SOUL_CHARS = 12000
MAX_LESSONS_CHARS = 8000
MAX_LESSON_CHARS = 240
MAX_AUTO_LESSONS = 40
Source = Literal["user", "director", "auto"]


class SoulLesson(BaseModel):
    id: str
    text: str
    source: Source = "auto"
    created_at: str


class DirectorSoul(BaseModel):
    id: str
    name: str
    description: str = ""
    builtin: bool = False
    markdown: str
    lessons: list[SoulLesson] = Field(default_factory=list)
    updated_at: str


def souls_root() -> Path:
    path = settings.data_dir / "souls"
    path.mkdir(parents=True, exist_ok=True)
    return path


def soul_dir(soul_id: str) -> Path:
    return souls_root() / soul_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    slug = slug[:48] or "soul"
    if not _SLUG_RE.match(slug):
        slug = f"soul-{uuid.uuid4().hex[:8]}"
    return slug


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(raw or "")
    meta: dict[str, str] = {}
    body = raw or ""
    if match:
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip().strip("\"'")
        body = raw[match.end() :]
    return meta, body.strip()


def _compose_markdown(name: str, description: str, body: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"{body.strip()}\n"
    )


def _lessons_path(soul_id: str) -> Path:
    return soul_dir(soul_id) / "lessons.json"


def _soul_md_path(soul_id: str) -> Path:
    return soul_dir(soul_id) / "soul.md"


def _load_lessons(soul_id: str) -> list[SoulLesson]:
    path = _lessons_path(soul_id)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = payload.get("lessons") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    lessons: list[SoulLesson] = []
    for item in items:
        try:
            lessons.append(SoulLesson.model_validate(item))
        except ValueError:
            continue
    return lessons


def _save_lessons(soul_id: str, lessons: list[SoulLesson]) -> None:
    path = _lessons_path(soul_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"lessons": [item.model_dump(mode="json") for item in lessons]},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _read_soul(soul_id: str) -> DirectorSoul | None:
    path = _soul_md_path(soul_id)
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    builtin = soul_id in BUILTIN_SOULS
    name = meta.get("name") or (BUILTIN_SOULS.get(soul_id, {}).get("name") if builtin else soul_id)
    description = meta.get("description") or (
        BUILTIN_SOULS.get(soul_id, {}).get("description") if builtin else ""
    )
    return DirectorSoul(
        id=soul_id,
        name=name,
        description=description,
        builtin=builtin,
        markdown=body,
        lessons=_load_lessons(soul_id),
        updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    )


def ensure_builtin_souls() -> None:
    for soul_id, spec in BUILTIN_SOULS.items():
        path = _soul_md_path(soul_id)
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _compose_markdown(spec["name"], spec["description"], spec["markdown"]),
            encoding="utf-8",
        )
        if not _lessons_path(soul_id).exists():
            _save_lessons(soul_id, [])


def list_souls() -> list[DirectorSoul]:
    ensure_builtin_souls()
    found: dict[str, DirectorSoul] = {}
    for child in sorted(souls_root().iterdir()):
        if not child.is_dir():
            continue
        soul = _read_soul(child.name)
        if soul is not None:
            found[soul.id] = soul
    for soul_id in BUILTIN_SOULS:
        if soul_id not in found:
            soul = _read_soul(soul_id)
            if soul is not None:
                found[soul_id] = soul
    order = list(BUILTIN_SOULS) + [soul_id for soul_id in found if soul_id not in BUILTIN_SOULS]
    return [found[soul_id] for soul_id in order if soul_id in found]


def get_soul(soul_id: str) -> DirectorSoul | None:
    ensure_builtin_souls()
    slug = (soul_id or "").strip()
    if not slug:
        return None
    return _read_soul(slug)


def default_soul_id() -> str:
    ensure_builtin_souls()
    return "studio"


def create_soul(*, name: str, markdown: str = "", description: str = "") -> DirectorSoul:
    ensure_builtin_souls()
    label = (name or "").strip()
    if not label:
        raise ValueError("name is required")
    slug = _slugify(label)
    if _soul_md_path(slug).exists():
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"
    body = (markdown or "").strip() or f"# {label}\n\nWrite this director's taste, blocking rules, and continuity habits here.\n"
    if len(body) > MAX_SOUL_CHARS:
        raise ValueError(f"soul.md must be at most {MAX_SOUL_CHARS} characters")
    desc = (description or "").strip()
    path = _soul_md_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_compose_markdown(label, desc, body), encoding="utf-8")
    _save_lessons(slug, [])
    soul = _read_soul(slug)
    if soul is None:
        raise ValueError("failed to create soul")
    return soul


def save_soul(
    soul_id: str,
    *,
    markdown: str | None = None,
    name: str | None = None,
    description: str | None = None,
    lessons_markdown: str | None = None,
) -> DirectorSoul:
    current = get_soul(soul_id)
    if current is None:
        raise ValueError(f"soul not found: {soul_id}")
    body = current.markdown if markdown is None else markdown.strip()
    if not body:
        raise ValueError("soul.md cannot be empty")
    if len(body) > MAX_SOUL_CHARS:
        raise ValueError(f"soul.md must be at most {MAX_SOUL_CHARS} characters")
    label = current.name if name is None else name.strip() or current.name
    desc = current.description if description is None else description.strip()
    _soul_md_path(soul_id).write_text(_compose_markdown(label, desc, body), encoding="utf-8")
    if lessons_markdown is not None:
        parsed: list[SoulLesson] = []
        now = _now()
        for line in lessons_markdown.splitlines():
            text = line.strip().lstrip("-").strip()
            if len(text) < 8:
                continue
            parsed.append(
                SoulLesson(
                    id=f"les_{uuid.uuid4().hex[:12]}",
                    text=text[:MAX_LESSON_CHARS],
                    source="user",
                    created_at=now,
                )
            )
        _save_lessons(soul_id, parsed[:MAX_AUTO_LESSONS])
    soul = _read_soul(soul_id)
    if soul is None:
        raise ValueError(f"soul not found: {soul_id}")
    return soul


def delete_soul(soul_id: str) -> None:
    if soul_id in BUILTIN_SOULS:
        raise ValueError("cannot delete a built-in soul")
    path = soul_dir(soul_id)
    if not path.exists():
        raise ValueError(f"soul not found: {soul_id}")
    import shutil

    shutil.rmtree(path)


def record_soul_lesson(
    soul_id: str,
    text: str,
    *,
    source: Source = "auto",
) -> SoulLesson | None:
    soul = get_soul(soul_id)
    if soul is None:
        return None
    clipped = re.sub(r"\s+", " ", (text or "").strip()).strip(" \"'`")
    if len(clipped) < 8:
        return None
    clipped = clipped[:MAX_LESSON_CHARS]
    needle = clipped.lower()
    for lesson in soul.lessons:
        hay = lesson.text.lower()
        if hay == needle or needle in hay or hay in needle:
            return lesson
    lessons = list(soul.lessons)
    while len(lessons) >= MAX_AUTO_LESSONS:
        auto_idx = next((i for i, item in enumerate(lessons) if item.source == "auto"), 0)
        lessons.pop(auto_idx)
    lesson = SoulLesson(
        id=f"les_{uuid.uuid4().hex[:12]}",
        text=clipped,
        source=source,
        created_at=_now(),
    )
    lessons.append(lesson)
    _save_lessons(soul_id, lessons)
    return lesson


def lessons_markdown(soul: DirectorSoul) -> str:
    if not soul.lessons:
        return ""
    return "\n".join(f"- {lesson.text}" for lesson in soul.lessons)


def soul_prompt_blocks(soul_id: str | None) -> str:
    slug = (soul_id or "").strip() or default_soul_id()
    soul = get_soul(slug)
    if soul is None:
        soul = get_soul(default_soul_id())
    if soul is None:
        return ""
    blocks = [
        "<DIRECTOR_SOUL>\n"
        f"name: {soul.name}\n"
        f"id: {soul.id}\n\n"
        f"{soul.markdown.strip()}\n"
        "</DIRECTOR_SOUL>"
    ]
    learned = lessons_markdown(soul)
    if learned:
        blocks.append(
            "<DIRECTOR_LESSONS>\n"
            "Craft this soul has learned across productions. Follow unless the user overrides it.\n"
            f"{learned}\n"
            "</DIRECTOR_LESSONS>"
        )
    return "\n\n".join(blocks)


def soul_worthy_lesson(text: str) -> bool:
    raw = text or ""
    if re.search(r"\bthis (production|film|project|story)\b", raw, re.I):
        return False
    return bool(
        re.search(
            r"\b(always|never|do not|don't|actors?|costume|wardrobe|create|invent)\b",
            raw,
            re.I,
        )
    )
