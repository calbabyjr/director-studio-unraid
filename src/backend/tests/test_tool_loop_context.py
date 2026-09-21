"""Keep native tool-loop follow-ups inside the model context window."""

from __future__ import annotations

import json

from app.agents.director.chat_orchestrator import (
    _compact_tool_loop_payload,
    _fit_tool_loop_conversation,
    _is_context_overflow,
)
from app.agents.director.chat import handle_chat
from app.core.projects.store import create_project
import pytest


def test_compact_tool_payload_drops_full_shot_dumps():
    payload = {
        "ok": True,
        "shot_id": "sht_a",
        "shot": {
            "id": "sht_a",
            "prompt_sections": {"detailed_description": "x" * 8000},
        },
        "notes": ["Wrote the six-section prompt for Shot 1."],
    }

    compact = _compact_tool_loop_payload(payload)

    encoded = json.dumps(compact)
    assert compact["ok"] is True
    assert compact["shot_id"] == "sht_a"
    assert compact["truncated"] is True
    assert "prompt_sections" not in encoded
    assert len(encoded) < 2000


def test_fit_conversation_keeps_latest_tools_and_summarizes_dropped_work():
    conversation = [
        {"role": "user", "content": "PROJECT_STATE\n" + ("s" * 200)},
    ]
    for index in range(8):
        conversation.append(
            {
                "role": "assistant",
                "content": "working",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {"name": f"write_prompt", "arguments": {"shot_id": f"sht_{index}"}},
                    }
                ],
            }
        )
        conversation.append(
            {
                "role": "tool",
                "tool_name": "write_prompt",
                "content": json.dumps({"ok": True, "notes": ["n" * 4000]}),
            }
        )

    fitted = _fit_tool_loop_conversation(conversation, max_chars=6000)
    encoded = json.dumps(fitted)
    assert fitted[0]["role"] == "user"
    assert fitted[0]["content"].startswith("PROJECT_STATE")
    assert any(
        item.get("role") == "user" and "already completed" in item.get("content", "")
        for item in fitted
    )
    assert fitted[-1]["role"] == "tool"
    assert len(encoded) < len(json.dumps(conversation))
    assert "write_prompt" in json.dumps(fitted)


def test_ollama_prompt_too_long_is_context_overflow():
    assert _is_context_overflow("prompt exceeds context length of 32768")
    assert _is_context_overflow("maximum context length exceeded")
    assert not _is_context_overflow("connection refused")


@pytest.mark.asyncio
async def test_follow_up_tool_messages_are_clipped_before_the_next_model_call(
    tmp_projects_dir,
):
    project = create_project("Clip loop", "INT. HALL\nKai waits.")
    seen: list[int] = []

    async def chat_fn(system: str, user: str, **kwargs):
        messages = kwargs.get("messages") or []
        if messages:
            seen.append(
                max(
                    (
                        len(item.get("content") or "")
                        for item in messages
                        if item.get("role") == "tool"
                    ),
                    default=0,
                )
            )
        if not messages:
            return {
                "content": "",
                "thinking": "",
                "tool_calls": [
                    {"name": "get_status", "arguments": {"shot_id": "missing"}}
                ],
            }
        return {
            "content": "Stopped after the compact tool result.",
            "thinking": "",
            "tool_calls": [],
        }

    result = await handle_chat(
        project_id=project.id,
        message="Check status.",
        svc=object(),
        chat_fn=chat_fn,
    )

    assert result.reply == "Stopped after the compact tool result."
    assert seen
    assert seen[0] < 4000
