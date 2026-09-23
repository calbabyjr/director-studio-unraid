"""Load on-demand Director guidance for a production stage."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path


GUIDE_IDS = frozenset(
    {
        "script-planning",
        "storyboard-validation",
        "reference-strategy",
        "reference-frame-generation",
        "visual-qc",
        "h3-prompt-writing",
        "video-qc",
        "sequence-assembly",
        *(
            "cinematography",
            "lighting-color",
            "blocking-continuity",
            "coverage-editing",
            "scene-craft",
            "sound-design",
        ),
    }
)

# Film-craft guides, loaded only on turns whose request touches their subject so
# the fixed Director envelope stays small. Order is priority when capped.
_CRAFT_TRIGGERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cinematography", re.compile(
        r"\b(?:shot|shots|framing|frame|lens|angle|camera|composition|close[- ]?up|wide|"
        r"layout|storyboard|reference frame|h3|prompt)\b", re.I)),
    ("lighting-color", re.compile(
        r"\b(?:light|lighting|lit|shadow|shadows|colou?r|mood|tone|grade|dark|bright|"
        r"layout|reference frame|h3|prompt)\b", re.I)),
    ("blocking-continuity", re.compile(
        r"\b(?:blocking|staging|position|continuity|eyeline|180|screen direction|"
        r"left|right|layout|storyboard|sequence)\b", re.I)),
    ("coverage-editing", re.compile(
        r"\b(?:storyboard|plan shots|coverage|sequence|cut|cuts|edit|editing|pacing|"
        r"rhythm|rough cut|assemble|shot list)\b", re.I)),
    ("scene-craft", re.compile(
        r"\b(?:script|screenplay|story|scene|beat|beats|dialogue|character|premise|"
        r"plot|draft)\b", re.I)),
    ("sound-design", re.compile(
        r"\b(?:sound|audio|music|score|soundscape|ambience|ambient|foley|silence|"
        r"voice|h3)\b", re.I)),
)
MAX_CRAFT_GUIDES = 3


def craft_guides_for_message(message: str, *, limit: int = MAX_CRAFT_GUIDES) -> tuple[str, ...]:
    """Pick at most ``limit`` film-craft guides relevant to this request."""
    text = message or ""
    return tuple(
        guide_id for guide_id, pattern in _CRAFT_TRIGGERS if pattern.search(text)
    )[:limit]


def _guides_dir() -> Path:
    return Path(__file__).with_name("guides")


def load_stage_guides(guide_ids: Iterable[str]) -> str:
    """Read requested stage guides from disk without caching their contents."""
    blocks: list[str] = []
    for guide_id in dict.fromkeys(guide_ids):
        if guide_id not in GUIDE_IDS:
            raise ValueError(f"unknown Director stage guide: {guide_id}")
        path = _guides_dir() / f"{guide_id}.md"
        try:
            body = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(
                f"Director stage guide could not be loaded: {guide_id}: {path}: {exc}"
            ) from exc
        if not body:
            raise RuntimeError(f"Director stage guide is empty: {guide_id}: {path}")
        blocks.append(
            f'<DIRECTOR_STAGE_GUIDE id="{guide_id}">\n{body}\n</DIRECTOR_STAGE_GUIDE>'
        )
    return "\n\n".join(blocks)
