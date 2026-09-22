"""User-editable Director workspace files: user.md plus additional markdown."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ...config import settings
from .templates import (
    AGENTS_FILENAME,
    DIRECTOR_TASKS_TEMPLATE,
    GLOBAL_AGENTS_TEMPLATE,
    PROJECT_AGENTS_TEMPLATE,
    PROJECT_TASKS_TEMPLATE,
    TASKS_FILENAME,
    USER_FILENAME,
    USER_TEMPLATE,
)

Scope = Literal["global", "project"]

MAX_FILE_CHARS = 8000
MAX_FILES_PER_SCOPE = 12
MAX_PROMPT_CHARS = 10000
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}\.md$")


class WorkspaceFile(BaseModel):
    name: str
    scope: Scope
    markdown: str
    reserved: bool
    placeholder: bool
    updated_at: str


def _normalize_name(name: str) -> str:
    raw = (name or "").strip()
    if raw and not raw.lower().endswith(".md"):
        raw = f"{raw}.md"
    return raw


def validate_name(name: str) -> str:
    normalized = _normalize_name(name)
    if not _NAME_RE.match(normalized):
        raise ValueError(
            "File name must be a simple markdown filename such as AGENTS.md or house-style.md"
        )
    return normalized


def is_reserved(name: str, scope: Scope) -> bool:
    key = validate_name(name).lower()
    if scope == "global":
        return key in {USER_FILENAME, AGENTS_FILENAME.lower(), TASKS_FILENAME.lower()}
    return key in {AGENTS_FILENAME.lower(), TASKS_FILENAME.lower()}


def human_workspace_root() -> Path:
    path = settings.data_dir / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def director_workspace_root(soul_id: str | None = None, project_id: str | None = None) -> Path:
    from ..souls.store import resolve_soul_id, soul_dir

    slug = resolve_soul_id(soul_id, project_id)
    path = soul_dir(slug) / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_root(
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> Path:
    if scope == "global":
        return director_workspace_root(soul_id, project_id)
    slug = (project_id or "").strip()
    if not slug:
        raise ValueError("project_id is required for project workspace files")
    from ..projects.store import project_dir

    path = project_dir(slug) / "workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_body(name: str, scope: Scope) -> str | None:
    key = name.lower()
    if scope == "global" and key == USER_FILENAME:
        return USER_TEMPLATE
    if key == AGENTS_FILENAME.lower():
        return GLOBAL_AGENTS_TEMPLATE if scope == "global" else PROJECT_AGENTS_TEMPLATE
    if key == TASKS_FILENAME.lower():
        return DIRECTOR_TASKS_TEMPLATE if scope == "global" else PROJECT_TASKS_TEMPLATE
    return None


def _is_placeholder(name: str, scope: Scope, markdown: str) -> bool:
    body = (markdown or "").strip()
    if not body:
        return True
    default = _default_body(name, scope)
    return default is not None and body == default.strip()


def _file_path(
    name: str,
    scope: Scope,
    project_id: str | None,
    soul_id: str | None = None,
) -> Path:
    filename = validate_name(name)
    if filename.lower() == USER_FILENAME:
        return human_workspace_root() / USER_FILENAME
    return workspace_root(scope, project_id, soul_id) / filename


def _read_file(path: Path, scope: Scope) -> WorkspaceFile | None:
    if not path.is_file():
        return None
    name = path.name
    markdown = path.read_text(encoding="utf-8")
    return WorkspaceFile(
        name=name,
        scope=scope,
        markdown=markdown,
        reserved=is_reserved(name, scope),
        placeholder=_is_placeholder(name, scope, markdown),
        updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    )


def ensure_defaults(
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> None:
    from ..souls.store import ensure_builtin_souls

    ensure_builtin_souls()
    if scope == "global":
        user_path = human_workspace_root() / USER_FILENAME
        if not user_path.exists():
            user_path.write_text(USER_TEMPLATE, encoding="utf-8")
    root = workspace_root(scope, project_id, soul_id)
    for name in (AGENTS_FILENAME, TASKS_FILENAME):
        path = root / name
        if not path.exists():
            path.write_text(_default_body(name, scope) or "", encoding="utf-8")


def list_files(
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> list[WorkspaceFile]:
    ensure_defaults(scope, project_id, soul_id)
    found: dict[str, WorkspaceFile] = {}
    if scope == "global":
        user = _read_file(human_workspace_root() / USER_FILENAME, scope)
        if user is not None:
            found[USER_FILENAME] = user
    for child in sorted(workspace_root(scope, project_id, soul_id).iterdir()):
        if not child.is_file() or child.suffix.lower() != ".md":
            continue
        try:
            validate_name(child.name)
        except ValueError:
            continue
        if child.name.lower() == USER_FILENAME:
            continue
        item = _read_file(child, scope)
        if item is not None:
            found[item.name.lower()] = item
    order = []
    if scope == "global":
        order.append(USER_FILENAME)
    order.append(AGENTS_FILENAME.lower())
    order.append(TASKS_FILENAME.lower())
    extras = sorted(key for key in found if key not in order)
    return [found[key] for key in order + extras if key in found]


def get_file(
    name: str,
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> WorkspaceFile | None:
    ensure_defaults(scope, project_id, soul_id)
    path = _file_path(name, scope, project_id, soul_id)
    if not path.is_file():
        needle = validate_name(name).lower()
        for item in list_files(scope, project_id, soul_id):
            if item.name.lower() == needle:
                return item
        return None
    return _read_file(path, scope)


def _close_tag(open_tag: str) -> str:
    name = open_tag[1:].split(None, 1)[0].rstrip(">")
    return f"</{name}>"


def save_file(
    name: str,
    markdown: str,
    *,
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
    create: bool = False,
) -> WorkspaceFile:
    ensure_defaults(scope, project_id, soul_id)
    filename = validate_name(name)
    if filename.lower() == USER_FILENAME and scope == "project":
        raise ValueError("user.md lives in Settings and is studio-wide")
    existing = get_file(filename, scope, project_id, soul_id)
    if create:
        if is_reserved(filename, scope):
            raise ValueError(f"{filename} already exists; edit it instead")
        if existing is not None:
            raise ValueError(f"{filename} already exists")
        if len(list_files(scope, project_id, soul_id)) >= MAX_FILES_PER_SCOPE:
            raise ValueError(f"at most {MAX_FILES_PER_SCOPE} workspace files per scope")
    elif existing is None:
        raise ValueError(f"workspace file not found: {filename}")
    body = markdown if markdown is not None else ""
    if len(body) > MAX_FILE_CHARS:
        raise ValueError(f"{filename} must be at most {MAX_FILE_CHARS} characters")
    path = _file_path(filename, scope, project_id, soul_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    saved = _read_file(path, scope)
    if saved is None:
        raise ValueError(f"failed to save {filename}")
    return saved


def delete_file(
    name: str,
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> None:
    filename = validate_name(name)
    if is_reserved(filename, scope):
        raise ValueError(f"cannot delete reserved workspace file: {filename}")
    path = _file_path(filename, scope, project_id, soul_id)
    if not path.is_file():
        current = get_file(filename, scope, project_id, soul_id)
        if current is None:
            raise ValueError(f"workspace file not found: {filename}")
        path = _file_path(current.name, scope, project_id, soul_id)
    path.unlink()


def _clip(text: str, limit: int) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[: max(0, limit - 1)].rstrip() + "…"


def workspace_prompt_blocks(
    project_id: str | None = None,
    soul_id: str | None = None,
) -> str:
    """USER plus this director's files, then this production's files."""
    from ..souls.store import resolve_soul_id

    slug = resolve_soul_id(soul_id, project_id)
    blocks: list[str] = []
    remaining = MAX_PROMPT_CHARS

    def append(tag: str, body: str) -> None:
        nonlocal remaining
        if remaining <= 0:
            return
        clipped = _clip(body, remaining)
        if not clipped:
            return
        blocks.append(f"{tag}\n{clipped}\n{_close_tag(tag)}")
        remaining -= len(clipped)

    user = get_file(USER_FILENAME, "global", soul_id=slug)
    if user is not None and not user.placeholder:
        append("<USER>", user.markdown)

    for item in list_files("global", soul_id=slug, project_id=project_id):
        if item.name.lower() == USER_FILENAME or item.placeholder:
            continue
        append(
            f'<DIRECTOR_WORKSPACE file="{item.name}" scope="director" soul="{slug}">',
            item.markdown,
        )

    if (project_id or "").strip():
        for item in list_files("project", project_id, soul_id=slug):
            if item.placeholder:
                continue
            append(
                f'<DIRECTOR_WORKSPACE file="{item.name}" scope="project">',
                item.markdown,
            )

    return "\n\n".join(blocks)
