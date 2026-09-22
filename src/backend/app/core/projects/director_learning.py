"""Recursive Director learning: journal plus compiled MEMORY.md.

Standing notes are the working set. MEMORY.md is the permanent textbook the
Director rereads every turn. Each learned rule is written back into MEMORY.md
so later turns compound earlier corrections.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

from ...config import settings
from ..paths import ensure_project_tree
from .director_memory import (
    DirectorMemoryNote,
    add_note,
    capture_user_memory,
    extract_memory_candidates,
)

Scope = Literal["project", "global"]

MAX_MEMORY_MD_CHARS = 6000
MAX_BULLET_CHARS = 240
MEMORY_HEADER = (
    "# Director memory\n\n"
    "Permanent learned rules. Follow unless the user overrides them this turn.\n"
)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)
_I_TOLD_YOU = re.compile(
    r"(?:i (?:already )?(?:told you|said)|as i (?:said|told you))[,:\s]+(.{8,220}?)(?:[.!]|remember|$)",
    re.I,
)
_WEAK_LESSON = re.compile(
    r"remember(?:\s+that|\s+this)?(?:\s+in the future)?|^to continue",
    re.I,
)
_YOU_KEEP = re.compile(
    r"you (?:keep|always|again)\s+(.{8,200})",
    re.I,
)
_CORRECTION_LEAD = re.compile(
    r"^(?:no[,.]?\s+|wrong[,.]?\s+|incorrect[,.]?\s+|that(?:'s| is) not\s+)",
    re.I,
)
_STOP_DOING = re.compile(
    r"\b(?:stop|quit) (?:doing )?(?:that|this|it)?[,:\s]+(.{8,200})",
    re.I,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).strip(" \"'`.,;:")


def memory_md_path(
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> Path:
    if scope == "global":
        from ..souls.store import ensure_builtin_souls, resolve_soul_id, soul_dir

        ensure_builtin_souls()
        slug = resolve_soul_id(soul_id, project_id)
        return soul_dir(slug) / "MEMORY.md"
    slug = (project_id or "").strip()
    if not slug:
        raise ValueError("project_id is required for project memory")
    ensure_project_tree(slug)
    return settings.projects_dir / slug / "agent" / "MEMORY.md"


def journal_path(
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> Path:
    if scope == "global":
        from ..souls.store import ensure_builtin_souls, resolve_soul_id, soul_dir

        ensure_builtin_souls()
        slug = resolve_soul_id(soul_id, project_id)
        return soul_dir(slug) / "journal.jsonl"
    slug = (project_id or "").strip()
    if not slug:
        raise ValueError("project_id is required for project memory")
    ensure_project_tree(slug)
    return settings.projects_dir / slug / "agent" / "journal.jsonl"


def read_memory_md(
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> str:
    path = memory_md_path(scope, project_id, soul_id)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_memory_md(
    markdown: str,
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> str:
    body = (markdown or "").strip()
    if len(body) > MAX_MEMORY_MD_CHARS:
        raise ValueError(f"MEMORY.md must be at most {MAX_MEMORY_MD_CHARS} characters")
    path = memory_md_path(scope, project_id, soul_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((body + "\n") if body else "", encoding="utf-8")
    return body


def memory_md_is_placeholder(markdown: str) -> bool:
    body = (markdown or "").strip()
    if not body:
        return True
    bullets = [match.group(1).strip() for match in _BULLET_RE.finditer(body)]
    return not any(len(item) >= 8 for item in bullets)


def _bullets(markdown: str) -> list[str]:
    return [_normalize(match.group(1)) for match in _BULLET_RE.finditer(markdown or "")]


def promote_lesson(
    text: str,
    *,
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> bool:
    """Append a unique bullet to MEMORY.md. Returns True when the file changed."""
    clipped = _normalize(text)[:MAX_BULLET_CHARS]
    if len(clipped) < 8:
        return False
    current = read_memory_md(scope, project_id, soul_id).strip() or MEMORY_HEADER.strip()
    existing = {_normalize(item).lower() for item in _bullets(current)}
    needle = clipped.lower()
    if needle in existing or any(needle in item or item in needle for item in existing if item):
        return False
    heading = "## This director" if scope == "global" else "## This production"
    if heading not in current:
        current = current.rstrip() + f"\n\n{heading}\n"
    updated = current.rstrip() + f"\n- {clipped}\n"
    if len(updated) > MAX_MEMORY_MD_CHARS:
        updated = _trim_oldest_bullets(updated, MAX_MEMORY_MD_CHARS)
    write_memory_md(updated, scope, project_id, soul_id)
    return True


def retract_lesson(
    text: str,
    *,
    scope: Scope,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> bool:
    clipped = _normalize(text).lower()
    if len(clipped) < 8:
        return False
    current = read_memory_md(scope, project_id, soul_id)
    if not current.strip():
        return False
    kept: list[str] = []
    removed = False
    for line in current.splitlines():
        match = _BULLET_RE.match(line)
        if match and clipped in _normalize(match.group(1)).lower():
            removed = True
            continue
        kept.append(line)
    if not removed:
        return False
    write_memory_md("\n".join(kept).strip(), scope, project_id, soul_id)
    return True


def _trim_oldest_bullets(markdown: str, limit: int) -> str:
    lines = markdown.splitlines()
    bullets = [index for index, line in enumerate(lines) if _BULLET_RE.match(line)]
    body = markdown
    while len(body) > limit and bullets:
        drop = bullets.pop(0)
        lines.pop(drop)
        bullets = [index if index < drop else index - 1 for index in bullets]
        body = "\n".join(lines)
    return body[:limit].rstrip()


def append_journal(
    *,
    text: str,
    scope: Scope,
    source: str,
    project_id: str | None = None,
    soul_id: str | None = None,
) -> None:
    path = journal_path(scope, project_id, soul_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "at": _now(),
        "scope": scope,
        "source": source,
        "project_id": project_id,
        "soul_id": soul_id,
        "text": _normalize(text)[:MAX_BULLET_CHARS],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def extract_turn_lessons(
    user_message: str,
    *,
    assistant_reply: str = "",
    actions: Iterable[str] | None = None,
) -> list[tuple[str, Scope]]:
    """Durable lessons from this turn. Assistant prose is not treated as a fact."""
    del assistant_reply, actions
    text = (user_message or "").strip()
    found: list[tuple[str, Scope]] = []
    seen: set[str] = set()

    def add(candidate: str, scope: Scope) -> None:
        clipped = _normalize(candidate)[:MAX_BULLET_CHARS]
        key = clipped.lower()
        if len(clipped) < 8 or key in seen or _WEAK_LESSON.search(clipped):
            return
        seen.add(key)
        found.append((clipped, scope))

    for candidate in extract_memory_candidates(text):
        add(candidate, "project")
    for pattern in (_I_TOLD_YOU, _YOU_KEEP, _STOP_DOING):
        for match in pattern.finditer(text):
            add(match.group(1), "global")
    if _CORRECTION_LEAD.search(text):
        rest = _CORRECTION_LEAD.sub("", text, count=1).strip()
        first = re.split(r"[.!?\n]", rest, maxsplit=1)[0].strip()
        add(first or rest[:MAX_BULLET_CHARS], "project")
    return found


def learn_from_turn(
    project_id: str,
    *,
    user_message: str,
    assistant_reply: str = "",
    actions: list[str] | None = None,
) -> list[DirectorMemoryNote]:
    """Capture this turn and fold extra corrections into permanent memory."""
    from ..souls.store import resolve_soul_id

    soul_id = resolve_soul_id(project_id=project_id)
    captured = list(capture_user_memory(project_id, user_message))
    extra = extract_turn_lessons(
        user_message,
        assistant_reply=assistant_reply,
        actions=actions,
    )
    for text, scope in extra:
        captured.append(
            add_note(
                text=text,
                scope=scope,
                source="auto",
                project_id=project_id,
                soul_id=soul_id,
            )
        )
    unique: list[DirectorMemoryNote] = []
    seen_ids: set[str] = set()
    for note in captured:
        if note.id in seen_ids:
            continue
        seen_ids.add(note.id)
        unique.append(note)
    try:
        from ..souls.store import record_soul_lesson, soul_worthy_lesson

        for note in unique:
            if soul_worthy_lesson(note.text):
                record_soul_lesson(soul_id, note.text, source="auto")
    except Exception:
        pass
    return unique


def compiled_memory_prompt(project_id: str, soul_id: str | None = None) -> str:
    from ..souls.store import resolve_soul_id

    slug = resolve_soul_id(soul_id, project_id)
    blocks: list[str] = []
    director_md = read_memory_md("global", project_id, slug)
    if not memory_md_is_placeholder(director_md):
        blocks.append(
            f'<DIRECTOR_MEMORY scope="director" soul="{slug}">\n'
            f"{director_md.strip()}\n"
            "</DIRECTOR_MEMORY>"
        )
    project_md = read_memory_md("project", project_id, slug)
    if not memory_md_is_placeholder(project_md):
        blocks.append(
            "<DIRECTOR_MEMORY scope=\"project\">\n"
            f"{project_md.strip()}\n"
            "</DIRECTOR_MEMORY>"
        )
    return "\n\n".join(blocks)


def memory_text_corpus(project_id: str, soul_id: str | None = None) -> str:
    from ..souls.store import resolve_soul_id

    slug = resolve_soul_id(soul_id, project_id)
    return "\n".join(
        part
        for part in (
            read_memory_md("global", project_id, slug),
            read_memory_md("project", project_id, slug),
        )
        if part
    )


def learn_from_turn_safe(
    project_id: str,
    *,
    user_message: str,
    assistant_reply: str = "",
    actions: list[str] | None = None,
) -> list[DirectorMemoryNote]:
    try:
        return learn_from_turn(
            project_id,
            user_message=user_message,
            assistant_reply=assistant_reply,
            actions=actions,
        )
    except Exception:
        return []
