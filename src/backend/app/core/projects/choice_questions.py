"""Multiple-choice questions the Director can present as checkboxes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ChoiceQuestion(BaseModel):
    prompt: str = Field(min_length=1, max_length=400)
    options: list[str] = Field(min_length=2, max_length=8)
    # Single choice (radio buttons) unless the Director allows several answers.
    allow_multiple: bool = False

    @field_validator("options")
    @classmethod
    def clean_options(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = " ".join(str(item or "").split())
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            cleaned.append(text[:160])
        if len(cleaned) < 2:
            raise ValueError("each question needs at least two options")
        return cleaned[:8]


def normalize_choice_questions(raw: Any) -> list[ChoiceQuestion]:
    if isinstance(raw, dict) and raw.get("options"):
        raw = [
            {
                "prompt": raw.get("prompt") or raw.get("question") or "Choose one",
                "options": raw.get("options"),
                "allow_multiple": raw.get("allow_multiple", False),
            }
        ]
    if not isinstance(raw, list):
        return []
    questions: list[ChoiceQuestion] = []
    for item in raw[:4]:
        if not isinstance(item, dict):
            continue
        try:
            questions.append(
                ChoiceQuestion(
                    prompt=str(item.get("prompt") or item.get("question") or "Choose one").strip() or "Choose one",
                    options=list(item.get("options") or []),
                    allow_multiple=bool(item.get("allow_multiple", False)),
                )
            )
        except Exception:
            continue
    return questions


def format_choice_answers(
    questions: list[ChoiceQuestion],
    selected: list[list[str]],
    extra: str = "",
) -> str:
    lines: list[str] = []
    for question, picks in zip(questions, selected):
        chosen = [item.strip() for item in picks if str(item).strip()]
        if not chosen:
            continue
        lines.append(f"{question.prompt}: {'; '.join(chosen)}")
    extra_text = extra.strip()
    if extra_text:
        lines.append(f"Also: {extra_text}")
    return "\n".join(lines).strip()
