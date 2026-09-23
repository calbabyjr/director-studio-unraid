"""Backend-owned context and capabilities for the optional Harness loop."""

from __future__ import annotations

import hashlib
import json
import math
import logging
import re
import shutil
import time
from typing import Any

from jsonschema import Draft202012Validator

from ...config import settings
from ...core.vram.orchestrator import GenerationActiveError
from ...core.projects.director_memory import apply_memory_to_system, capture_user_memory
from ...core.projects.store import list_shots, load_project
from .chat_context import project_context_blob, gpt_generation_context_blob
from .chat_orchestrator import (
    DIRECTOR_CHAT_SYSTEM, ChatResult, _StoryboardSubmissionBudget,
    _claims_completed_storyboard, _claims_pending_tool, _layout_images,
    _requested_minimum_duration_s, pending_tool_continuation,
    sanitize_tools_for_pipeline,
)
from .harness_client import HarnessClient, HarnessError
from .intent import actor_design_intent, explicit_gpt_image_intent
from .planner import AppendShotSubmission, ShotRevisionSubmission
from .tool_schema import director_chat_guides, director_tool_schemas, IMAGE_TOOLS
from .skill_loader import with_director_skill


# Vision bytes stay in Python, outside the native text meter. Reserve a labelled
# conservative allowance, not a claim about the model's exact image tokenizer.
IMAGE_TOKEN_RESERVE = 2048

logger = logging.getLogger("director_studio.director.harness")

# Seeded history is plain text: tool calls and results are gone. A model that
# sees its own "I'll queue the Layout now…" replies imitates them in prose (and
# copies any label put on them) instead of emitting the tool call, so such
# replies are dropped from the seed; PROJECT_STATE carries what actually ran.
_ANNOUNCED_ACTION = re.compile(
    r"(?:i['’]ll|i will|let me|i['’]m going to|going to)\s+(?:now\s+)?"
    r"(?:queue|inspect|write|create|run|append|revise|generate|review|add|update|bind|cast)\b"
    r"|\b(?:queueing|inspecting|writing|creating|generating|reviewing)\b[^\n]{0,80}(?:\bnow\b|\.\.\.|…)",
    re.I,
)
# A reply that asks the user something stays: their next answer ("go with A",
# "yes") is meaningless without it.
_ASKS_USER = re.compile(
    r"\?|\b(?:which (?:do|would)|do you want|would you like|shall i|should i|reply with|choose|prefer)\b",
    re.I,
)
# Written by an earlier version of this seed filter; models echoed it verbatim.
_UNCONFIRMED_PREFIX = "[Prose only"
PATROL_PREFIX = "Memory check —"
# Recent turns only: long prose-only stretches teach the model to loop.
SEED_MAX_ROWS = 12


def _seed_row(row: dict) -> dict | None:
    content = row["content"]
    if row["role"] != "assistant":
        return row
    if content.startswith((PATROL_PREFIX, _UNCONFIRMED_PREFIX)):
        return None  # regenerable reminders / echoed labels crowd out real turns
    if (_ANNOUNCED_ACTION.search(content) or _claims_pending_tool(content)) and not _ASKS_USER.search(content):
        return None
    return row


def harness_input_budget(context_capacity: int, image_count: int = 0) -> int:
    budget = context_capacity - settings.director_num_predict - image_count * IMAGE_TOKEN_RESERVE
    if budget < 256:
        raise ValueError("Current images and output allowance leave no usable context budget; send fewer images.")
    return budget


def bounded_harness_history(rows: list | None, budget_tokens: int) -> list[dict]:
    """Keep the newest chat rows that fit a fraction of the Harness input budget.

    Harness TokenMeter uses ~4 characters per token. A 32k local window cannot
    summarize a 400-message session in one pass; sending the full native
    transcript makes compaction abort the turn.
    """
    clean = [
        seeded
        for row in (rows or [])
        if isinstance(row, dict)
        and row.get("role") in {"user", "assistant"}
        and isinstance(row.get("content"), str)
        and (seeded := _seed_row({"role": row["role"], "content": row["content"]})) is not None
    ]
    omitted_by_count = max(0, len(clean) - SEED_MAX_ROWS)
    clean = clean[-SEED_MAX_ROWS:]
    if not clean:
        return []
    budget_chars = max(4000, int(budget_tokens * 4 * 0.35))
    kept: list[dict] = []
    used = 0
    for row in reversed(clean):
        size = len(row["content"])
        if kept and used + size > budget_chars:
            break
        kept.append(row)
        used += size
    kept.reverse()
    omitted = len(clean) - len(kept) + omitted_by_count
    if omitted <= 0:
        return kept
    return [
        {
            "role": "user",
            "content": (
                f"[Earlier Director chat omitted {omitted} messages because they exceeded "
                f"the {budget_tokens}-token working window. Use current project facts and "
                "the recent turns.]"
            ),
        },
        {
            "role": "assistant",
            "content": "Understood. I will use the current project and the recent conversation.",
        },
        *kept,
    ]


_UNKNOWN_TOOL = re.compile(r'unknown tool "([A-Za-z0-9_]+)"')
# Tools withheld unless the user's current message explicitly authorizes them.
_TOOL_AUTHORIZATION_HINTS = {
    "queue_ref_frame": 'Layout generation needs an explicit go-ahead in the user\'s message, e.g. "Generate the Layout" or "Queue the Layout now".',
    "revise_ref_frame": 'Layout revision needs an explicit go-ahead in the user\'s message, e.g. "Regenerate the Layout".',
    "queue_gpt_ref_frame": 'GPT Layout generation needs an explicit go-ahead in the user\'s message, e.g. "Generate the Layout with GPT".',
    "queue_h3": 'Video generation needs an explicit go-ahead in the user\'s message, e.g. "Generate the H3 video for Shot 1".',
    "extract_clip_tail_frame": 'Tail-frame extraction needs an explicit request, e.g. "Use the last frame of Shot 1 as the Layout".',
    "assemble_sequence": 'Sequence assembly needs an explicit request, e.g. "Assemble the sequence".',
}


def _current_turn(messages: list[dict]) -> list[dict]:
    """Messages from the user's current request on (the saved session holds all turns)."""
    for index in range(len(messages) - 1, -1, -1):
        item = messages[index]
        if item.get("role") == "user" and not str(item.get("content") or "").startswith("[Backend]"):
            return messages[index:]
    return messages


def _unavailable_tool_calls(messages: list[dict]) -> list[str]:
    names: list[str] = []
    for message in _current_turn(messages):
        if message.get("role") != "tool":
            continue
        for name in _UNKNOWN_TOOL.findall(str(message.get("content") or "")):
            if name not in names:
                names.append(name)
    return names


def _unavailable_tool_guidance(names: list[str]) -> str:
    hints = [_TOOL_AUTHORIZATION_HINTS[n] for n in names if n in _TOOL_AUTHORIZATION_HINTS]
    return (
        f"[Backend] {', '.join(names)} is not available in this turn, so nothing was queued. "
        + (" ".join(hints) + " " if hints else "")
        + "Do not call any tool again this turn. Reply to the user: summarize exactly what you "
        "would do (shot, purpose, visual state, source references) and tell them the phrase "
        "that authorizes it."
    )


_COMMAND_START = re.compile(
    r"(?:^|[.!;\n]\s*)(?:(?:ok(?:ay)?|yes|now|please|go ahead and|so)[,\s]+)*"
    r"(?:generate|regenerate|queue|make|render|create|run)\b",
    re.I,
)
_COMMAND_HEDGE = re.compile(
    r"\?|\b(?:not|never|don't|dont|doesn't|won't|before|after|until|make sure|should|"
    r"would|could|whether|if|maybe|later)\b",
    re.I,
)


def _explicit_generation_command(message: str) -> bool:
    """Stricter than tool gating: only an unhedged imperative earns a forced retry."""
    from .intent import normalize_text

    text = normalize_text(message)
    return bool(_COMMAND_START.search(text)) and not _COMMAND_HEDGE.search(text)


def _authorized_generation_tool(message: str, offered_tools: list[dict], messages: list[dict]) -> str | None:
    """Generation tool the user explicitly asked for this turn that has not run yet."""
    from .intent import explicit_h3_generation_intent, explicit_layout_generation_intent

    if not _explicit_generation_command(message):
        return None
    offered = {str(t.get("function", {}).get("name") or "") for t in offered_tools or []}
    called = {
        str(call.get("function", {}).get("name") or "")
        for item in _current_turn(messages)
        for call in (item.get("tool_calls") or [])
    }
    for name, wanted in (
        ("queue_ref_frame", explicit_layout_generation_intent(message)),
        ("queue_h3", explicit_h3_generation_intent(message)),
    ):
        if wanted and name in offered and name not in called:
            return name
    return None


class BackendTurn:
    """A bounded, process-local turn, never a second project or session store."""

    def __init__(self, project_id, message, svc, chat_fn, *, images=None, captions=None, on_progress=None, compact_only=False, history=None):
        self.project_id, self.message = project_id, message
        self.compact_only = compact_only
        self.seed_history = list(history or [])
        self.svc, self.chat_fn, self.on_progress = svc, chat_fn, on_progress
        self.images = list(images or [])
        self.captions = list(captions or [])
        self.uploads = [
            {"image_index": i, "filename": self.captions[i-1] if i <= len(self.captions) else f"image-{i}.png", "data_b64": data}
            for i, data in enumerate(self.images, 1)
        ]
        self.actions: list[str] = []
        self.result_images = []
        self.touched: set[str] = set()
        self.notes: list[str] = []
        self.budget = _StoryboardSubmissionBudget()
        self.call_ids: set[str] = set()
        self.calls: set[tuple[str, str]] = set()
        self.successful_prompt_shot_ids: set[str] = set()
        self.storyboard_failed = False
        self.terminal_failure: str | None = None
        self.expected_state: str | None = None
        self.local_generation_receipt: str | None = None
        self.offered_context: dict | None = None
        self.offered_version: str | None = None
        self.pending_choices: list = []

    def snapshot(self):
        project = load_project(self.project_id)
        if project is None:
            raise ValueError("Project not found")
        shots = list_shots(self.project_id)
        project_state = project.model_dump(mode="json")
        # Store writes refresh this display timestamp even for a semantic no-op.
        # Dedupe and stale-inference authority follow content, not filesystem time.
        project_state.pop("updated_at", None)
        version = hashlib.sha256(json.dumps(
            [project_state, [s.model_dump(mode="json") for s in shots]],
            sort_keys=True, ensure_ascii=False,
        ).encode()).hexdigest()
        return project, shots, version

    def context(self):
        project, shots, version = self.snapshot()
        pending = any(not isinstance(u.get("classification"), dict) for u in self.uploads)
        tools = director_tool_schemas(
            project, current_message=self.message,
            allow_save_storyboard=not self.budget.exhausted,
            include_chat_image_import=pending,
        )
        if not pending and _needs_fresh_storyboard(project, shots):
            tools = [
                tool for tool in tools
                if tool["function"]["name"] not in IMAGE_TOOLS
            ]
            if not any(tool["function"]["name"] == "save_storyboard" for tool in tools):
                catalog = director_tool_schemas(
                    project,
                    current_message="",
                    allow_save_storyboard=not self.budget.exhausted,
                )
                replacement = next(
                    (tool for tool in catalog if tool["function"]["name"] == "save_storyboard"),
                    None,
                )
                if replacement is not None:
                    tools.append(replacement)
        if self.terminal_failure:
            tools = []
        elif self.storyboard_failed and self.budget.exhausted:
            tools = [tool for tool in tools if tool["function"]["name"] in {"get_status", "inspect_asset"}]
        state = (gpt_generation_context_blob(project, shots, self.message)
                 if explicit_gpt_image_intent(self.message) and not actor_design_intent(self.message)
                 else project_context_blob(project, shots, message=self.message, focused=True))
        from ...core.souls.context import bind_soul_for_project

        bind_soul_for_project(self.project_id)
        capture_user_memory(self.project_id, self.message)
        system = apply_memory_to_system(DIRECTOR_CHAT_SYSTEM, self.project_id)
        if self.images:
            system += "\nInspect the images attached by the backend."
            if self.uploads:
                system += " Classify every uploaded image before unrelated changes."
        if self.terminal_failure:
            system += (
                "\nA derived prompt operation already failed after its bounded internal "
                "repair attempts. Explain the confirmed failure and the unchanged project "
                "state. Do not alter the script, storyboard, dialogue, references, or Layouts "
                "to work around it in this turn."
            )
        elif self.storyboard_failed and self.budget.exhausted:
            system += "\nStoryboard revision budget exhausted after failed saves. Read state if needed, then explain the unresolved issue. No further project changes this turn."
        system = with_director_skill(system, guides=director_chat_guides(
            project, include_visual_qc=bool(self.images), current_message=self.message,
        ))
        self.offered_context = {"system": system, "state": state, "tools": tools}
        self.offered_version = version
        return self.offered_context

    async def dispatch(self, method: str, params: dict):
        if self.compact_only and (method == "tool" or (method == "llm" and params.get("purpose") != "compaction")):
            raise ValueError("Manual compaction cannot execute tools or business inference")
        if method == "context":
            if params.get("include_history") is True:
                return {"history": self.seed_history}
            if self.expected_state is None:
                self.expected_state = self.snapshot()[2]
            return self.context()
        if method == "llm":
            return await self.infer(params)
        if method == "tool":
            return await self.tool(params)
        raise ValueError("Unknown Harness capability")

    async def infer(self, params):
        if self.chat_fn is None:
            raise ValueError("No Director inference provider is available")
        purpose = params.get("purpose", "turn")
        if purpose not in {"turn", "compaction"}:
            raise ValueError("Invalid inference purpose")
        max_output = params.get("max_output_tokens")
        if max_output is not None and (type(max_output) is not int or not 1 <= max_output <= 131072):
            raise ValueError("Invalid inference output budget")
        raw = params.get("messages")
        if not isinstance(raw, list) or not raw or len(raw) > 11000:
            raise ValueError("Invalid Harness message list")
        messages = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("Invalid Harness message")
            if item.get("role") == "system":
                continue
            if item.get("role") not in {"user", "assistant", "tool"} or not isinstance(item.get("content", ""), str):
                raise ValueError("Harness messages must be text and tool records")
            clean = {k: v for k, v in item.items() if k in {"role", "content", "tool_calls", "tool_call_id", "tool_name"}}
            if "tool_calls" in clean:
                normalized = []
                for call in clean["tool_calls"]:
                    function = dict(call["function"])
                    arguments = function.get("arguments", {})
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool arguments must be an object")
                    function["arguments"] = arguments
                    normalized.append({"id": call["id"], "type": "function", "function": function})
                clean["tool_calls"] = normalized
            messages.append(clean)
        if not messages:
            raise ValueError("Harness conversation is empty")
        tool_names = {call["id"]: call["function"]["name"] for m in messages for call in m.get("tool_calls", [])}
        for m in messages:
            if m["role"] == "tool" and m.get("tool_call_id") in tool_names:
                m["tool_name"] = tool_names[m["tool_call_id"]]
        context = self.offered_context or self.context()
        project, _, version = self.snapshot()
        compacting = purpose == "compaction"
        if not compacting:
            # Bind authority to the context the model actually read, not a newer
            # project revision that arrived while the request was being prepared.
            self.expected_state = self.offered_version
        system = ("Summarize conversation history concisely. Preserve user decisions, creative constraints, unresolved questions and confirmed tool outcomes. Do not invent successful actions. Current project facts are supplied separately by the backend."
                  if compacting else context["system"] + "\n\nPROJECT_STATE:\n" + context["state"])
        offered_tools = [] if compacting else context["tools"]
        if not compacting and "system" in params and params["system"] != system:
            raise ValueError("Harness system envelope does not match the issued backend context")
        if not compacting and "tools" in params:
            schemas = params["tools"]
            names = {tool["function"]["name"] for tool in offered_tools}
            if (not isinstance(schemas, list) or any(not isinstance(t, dict) or
                    not isinstance(t.get("name"), str) or not isinstance(t.get("parameters"), dict)
                    for t in schemas) or len(schemas) != len(names)
                    or {t["name"] for t in schemas} != names):
                raise ValueError("Harness tool envelope does not match the issued backend catalog")
            # Presentation schemas are the same normalized schemas Harness metered.
            # Original Python schemas remain authoritative in tool().
            offered_tools = [{"type": "function", "function": {
                "name": t["name"], "description": t.get("description", ""), "parameters": t["parameters"],
            }} for t in schemas]
        if not compacting:
            blocked = _unavailable_tool_calls(messages)
            if blocked:
                # A model that calls a tool this turn does not offer gets a bare
                # "unknown tool" error and tends to retry it until MAX_STEPS.
                # Take tools away and have it answer the user instead.
                offered_tools = []
                messages.append({"role": "user", "content": _unavailable_tool_guidance(blocked)})
        if self.images and not compacting:
            # Bytes are never sent to Node. Always hydrate the latest user message locally.
            for message in reversed(messages):
                if message["role"] == "user":
                    message["images"] = self.images
                    break
        infer_kwargs = {
            "tools": offered_tools,
            "images": None if compacting else self.images or None,
            "require_vision": bool(self.images) and not compacting,
            "inference_purpose": purpose,
            "prepared_system": True,
            "guides": () if compacting else director_chat_guides(
                project, include_visual_qc=bool(self.images), current_message=self.message
            ),
        }
        if max_output is not None:
            infer_kwargs["max_output_tokens"] = min(max_output, settings.director_num_predict)
        try:
            result = await self.chat_fn(system, self.message, messages=messages, **infer_kwargs)
        except GenerationActiveError:
            if compacting or not self.local_generation_receipt:
                raise
            result = {
                "content": self.local_generation_receipt,
                "thinking": "",
                "tool_calls": [],
            }
        if not isinstance(result, dict):
            raise ValueError("Harness requires native model tool responses")
        content = str(result.get("content") or "")
        if (
            not compacting
            and not (result.get("tool_calls") or [])
            and _claims_pending_tool(content)
        ):
            follow = [dict(item) for item in messages]
            follow.append({"role": "assistant", "content": content})
            follow.append({"role": "user", "content": pending_tool_continuation(content)})
            retry = await self.chat_fn(system, self.message, messages=follow, **infer_kwargs)
            if isinstance(retry, dict):
                result = retry
        elif not compacting and not (result.get("tool_calls") or []):
            authorized = _authorized_generation_tool(self.message, offered_tools, messages)
            if authorized:
                # The user explicitly asked for this generation and the tool is
                # offered, but the model answered with another summary. Ask once.
                follow = [dict(item) for item in messages]
                follow.append({"role": "assistant", "content": content})
                follow.append({"role": "user", "content": (
                    f"[Backend] The user's current message explicitly authorizes this generation. "
                    f"Call {authorized} now with the exact shot and source references already "
                    "discussed (from PROJECT_STATE). Do not summarize or ask again."
                )})
                retry = await self.chat_fn(system, self.message, messages=follow, **infer_kwargs)
                if isinstance(retry, dict):
                    result = retry
        return result

    async def tool(self, params):
        from .chat import _run_tools

        name, args, call_id = params.get("name"), params.get("arguments"), params.get("call_id")
        if not isinstance(name, str) or not isinstance(args, dict) or not isinstance(call_id, str) or not call_id:
            return {"ok": False, "error": "Tool name, object arguments and call_id are required"}
        if call_id in self.call_ids:
            return {"ok": False, "error": "Repeated call rejected. Inspect the existing outcome; do not replay a mutation."}
        if self.terminal_failure:
            return {"ok": False, "retryable": False, "error": self.terminal_failure}
        fingerprint = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        # One model step may request many legitimate shot edits. Keep its
        # inference limit separate from this bounded per-turn admission budget.
        if len(self.call_ids) >= settings.harness_max_tool_calls:
            return {"ok": False, "error": "Turn tool limit reached. No further tools can run in this turn; report completed and pending work without retrying."}
        self.call_ids.add(call_id)
        prompt_shot_id = args.get("shot_id") if name == "write_prompt" else None
        if (
            isinstance(prompt_shot_id, str)
            and prompt_shot_id in self.successful_prompt_shot_ids
        ):
            return {
                "ok": True,
                "already_saved": True,
                "shot_id": prompt_shot_id,
                "notes": [
                    "Prompt already saved for this Shot in the current turn; "
                    "the duplicate write_prompt call made no changes."
                ],
            }
        context = self.context()
        schema = next((s["function"] for s in context["tools"] if s["function"]["name"] == name), None)
        if schema is None:
            return {"ok": False, "error": f"Tool is not currently offered: {name}"}
        raw_fingerprint = fingerprint
        if name == "append_shot":
            try:
                args = AppendShotSubmission.model_validate(args).model_dump(mode="json", exclude_unset=True)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            fingerprint = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        if name == "revise_shot":
            try:
                # Use the same partial-update model as the business handler;
                # never materialize defaults for fields the user did not edit.
                if isinstance(args.get("duration_s"), bool):
                    raise ValueError("duration_s must be a number, not a boolean")
                revision = ShotRevisionSubmission.model_validate(args)
                if revision.duration_s is not None and not math.isfinite(revision.duration_s):
                    raise ValueError("duration_s must be finite")
                args = revision.model_dump(mode="json", exclude_unset=True)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            fingerprint = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        errors = list(Draft202012Validator(schema["parameters"]).iter_errors(args))
        if errors:
            return {"ok": False, "error": errors[0].message}
        project, shots, version = self.snapshot()
        if name not in {"get_status", "inspect_asset"} and (
            (version, raw_fingerprint) in self.calls
            or (version, fingerprint) in self.calls
        ):
            return {"ok": False, "error": "Repeated call rejected. Inspect the existing outcome; do not replay a mutation."}
        if self.expected_state is not None and version != self.expected_state:
            return {"ok": False, "error": "Project changed since inference. Refresh context and reconsider the call."}
        if self.storyboard_failed and name in IMAGE_TOOLS:
            return {"ok": False, "error": "Storyboard save failed; save a valid storyboard before image or prompt work"}
        requested = {"name": name, "args": args}
        safe, _ = sanitize_tools_for_pipeline([requested], project=project, shots=shots)
        # The compatibility sanitizer can insert planning calls. Harness selects every
        # tool itself; only validate the requested call, never execute injected work.
        if requested not in safe:
            return {"ok": False, "error": "Current project state blocks this tool; refresh the project context"}
        payloads: list[dict[str, Any]] = []
        before = len(self.actions)
        # Only execution makes a mutation's outcome potentially unknown. Schema,
        # availability and stale-state rejections are safe for fresh inference to repair.
        self.calls.update(((version, raw_fingerprint), (version, fingerprint)))
        notes, touched = await _run_tools(
            project_id=self.project_id, tools=[requested], svc=self.svc,
            actions=self.actions, on_progress=self.on_progress, result_payloads=payloads,
            user_feedback=self.message, requested_minimum_duration_s=_requested_minimum_duration_s(self.message),
            storyboard_budget=self.budget, images=self.result_images, user_uploads=self.uploads,
        )
        self.notes.extend(notes)
        self.touched |= touched
        result = {"ok": True, "notes": notes}
        for payload in payloads:
            result.update(payload)
            if payload.get("choices"):
                self.pending_choices = list(payload["choices"])
        if result["ok"] and len(self.actions) == before and not payloads:
            result.update(ok=False, error="No successful operation confirmed. " + " ".join(notes))
        if name == "save_storyboard":
            self.storyboard_failed = not result["ok"]
        if name == "write_prompt" and not result["ok"]:
            failure = str(result.get("error") or "Prompt generation failed.")
            self.terminal_failure = (
                "Prompt generation did not complete after bounded internal repair. "
                f"The saved storyboard was not changed to work around it. {failure}"
            )
            result.update(retryable=False, code="PROMPT_GENERATION_FAILED")
        elif name == "write_prompt" and result["ok"]:
            saved_shot_id = result.get("shot_id") or args.get("shot_id")
            if isinstance(saved_shot_id, str) and saved_shot_id:
                self.successful_prompt_shot_ids.add(saved_shot_id)
        completed_actions = self.actions[before:]
        if result["ok"] and any(
            action == "ref_frame_all" or action.startswith("ref_frame:")
            for action in completed_actions
        ):
            self.local_generation_receipt = " ".join(notes).strip()
        self.expected_state = self.snapshot()[2]
        return result

    def finish(self, result):
        project, shots, _ = self.snapshot()
        reply = result["reply"]
        if self.terminal_failure and re.search(r"<tool_call\b", reply, re.IGNORECASE):
            reply = re.split(r"<tool_call\b", reply, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            reply = (reply or self.terminal_failure) + (
                "\n\nA text-form tool call appeared after the failure, but it was not "
                "executed and did not change project state."
            )
        if self.terminal_failure:
            saved = f"Storyboard saved: {len(shots)} shots. " if "save_storyboard" in self.actions else ""
            completed = [action.split(":", 1)[1] for action in self.actions if action.startswith("write_prompt:")]
            prompt_status = f"Prompts saved for: {', '.join(completed)}. " if completed else ""
            reply = saved + prompt_status + self.terminal_failure + (
                "\n\nA text-form tool call appeared after the failure, but it was not executed "
                "and did not change project state." if "not executed" in reply else ""
            )
        elif "save_storyboard" in self.actions:
            # Keep the model's explanation and partial-work details. A successful
            # save is only one operation, not proof that the entire turn finished.
            reply = f"Storyboard saved: {len(shots)} shots.\n\n" + reply
        elif "append_shot" in self.actions and _claims_completed_storyboard(reply):
            count = self.actions.count("append_shot")
            reply = f"Appended {count} new shot{'s' if count != 1 else ''} at the end."
        elif self.storyboard_failed and "append_shot" not in self.actions:
            reply = "Storyboard was not saved. " + (" ".join(self.notes) or "No successful storyboard operation was confirmed.")
        elif _claims_completed_storyboard(reply):
            reply = "No storyboard save was confirmed in this turn."
        images = self.result_images + _layout_images(shots, only_shot_ids=self.touched) if self.touched else self.result_images
        try:
            from ...core.projects.director_learning import learn_from_turn

            learn_from_turn(
                self.project_id,
                user_message=self.message,
                assistant_reply=reply,
                actions=self.actions,
            )
        except Exception:
            pass
        return ChatResult(reply=reply, project=project, shots=shots, actions=self.actions,
                          images=images, thinking=result.get("thinking", ""), steps=self.notes,
                          choices=list(self.pending_choices))


async def handle_harness_chat(*, project_id, message, svc, chat_fn=None, history=None,
                              on_progress=None, user_images_b64=None, user_image_captions=None,
                              context_capacity=None):
    context_capacity = context_capacity or settings.director_num_ctx
    turn = BackendTurn(project_id, message, svc, chat_fn, images=user_images_b64,
                       captions=user_image_captions, on_progress=on_progress, history=history)
    # Reuse Python's existing visual preparation; sidecar receives no file paths/bytes.
    if not turn.images:
        from .vision import collect_vision_attachments, wants_vision, layout_reference_ids_from_message

        shots = list_shots(project_id)
        layout_ids = layout_reference_ids_from_message(message, shots)
        if wants_vision(message) or layout_ids:
            pack = collect_vision_attachments(project_id=project_id, shots=shots, message=message, layout_ref_ids=layout_ids or None)
            turn.images = list(pack.get("images_b64") or [])
    budget = harness_input_budget(context_capacity, len(turn.images))
    seed = bounded_harness_history(history, budget)
    turn.seed_history = seed

    async def _run(session_id: str, rows: list[dict]) -> dict:
        return await HarnessClient(
            settings.harness_base_url,
            settings.harness_internal_token,
            timeout=settings.harness_turn_timeout_sec,
        ).run(
            {
                "message": message,
                "history": rows,
                "session_id": session_id,
                # Harness meters prompt pressure. Reserve the provider-reported
                # completion allowance so long history is compacted before it can
                # consume the space Qwen needs to finish reasoning and tool output.
                "context_window": budget,
                "max_steps": settings.harness_max_steps,
            },
            turn.dispatch,
            on_progress,
        )

    try:
        result = await _run(harness_session_id(project_id), [])
    except HarnessError as exc:
        if exc.code == "COMPACTION_FAILED":
            # A transient GPU refusal says nothing about the session's size, so
            # keep it. Anything else means the saved session can no longer be
            # summarized in this window and will fail every turn: retire it and
            # restart the stable session from recent turns.
            transient = _compaction_failure_transient(exc)
            if not transient:
                archive_harness_session(project_id, reason=str(exc))
            if on_progress:
                await on_progress({
                    "type": "runtime",
                    "text": (
                        "History could not be summarized while the GPU is busy; continuing from recent turns."
                        if transient else
                        "Chat memory outgrew the model window; archived it and started a fresh working session from recent turns."
                    ),
                })
            retry_id = (harness_session_id(project_id, nonce=str(time.time_ns()))
                        if transient else harness_session_id(project_id))
            try:
                result = await _run(retry_id, seed)
            except HarnessError as retry_exc:
                if retry_exc.code != "COMPACTION_FAILED":
                    raise
                if not transient:
                    archive_harness_session(project_id, reason=str(retry_exc))
                if on_progress:
                    await on_progress({
                        "type": "runtime",
                        "text": "Continuing without prior chat turns in this working window.",
                    })
                result = await _run(retry_id if not transient
                                    else harness_session_id(project_id, nonce=str(time.time_ns())), [])
        elif exc.code != "MAX_STEPS":
            raise
        else:
            confirmed = " ".join(turn.notes[-3:]).strip()
            detail = (
                f" Last confirmed issue: {turn.terminal_failure}"
                if turn.terminal_failure
                else f" Confirmed before stopping: {confirmed}" if confirmed else ""
            )
            result = {
                "reply": (
                    "I couldn't safely complete this request in one turn. Any listed tool "
                    "results were preserved; any additional action is not confirmed."
                    f"{detail} Please continue with the specific pending step you want next."
                ),
                "thinking": "",
            }
    return turn.finish(result)


def _needs_fresh_storyboard(project, shots) -> bool:
    from .context_io import load_agent_context
    from .service import _script_hash

    script = (project.script_text or "").strip()
    if not script:
        return False
    planned = load_agent_context(project.id)
    planned_hash = (planned.script_hash if planned else "") or ""
    return not shots or planned_hash != _script_hash(script)


# Compaction failures that mean the saved session itself can no longer be
# summarized in this window. Anything else (GPU busy, Ollama timeout/restart)
# is transient and must not cost the project its native history.
_SESSION_TOO_LARGE_MARKERS = (
    "truncated at the token cap",
    "summary is not smaller",
    "Overflow recovery failed",
    "Legacy context migration failed",
)


# "summary is not smaller than the shadowed content (N ...)" with a small N
# means the history is too SHORT to shrink: the fixed envelope, not the
# session, is filling the window. Archiving the session cannot help then.
_SMALL_SHADOWED_TOKENS = 4000
_SHADOWED = re.compile(r"shadowed content \((\d+) estimated")


def _compaction_failure_transient(exc: HarnessError) -> bool:
    text = str(exc)
    shadowed = _SHADOWED.search(text)
    if shadowed and int(shadowed.group(1)) < _SMALL_SHADOWED_TOKENS:
        return True
    return not any(marker in text for marker in _SESSION_TOO_LARGE_MARKERS)


def archive_harness_session(project_id: str, *, reason: str = "") -> bool:
    """Move the project's stable Harness session aside; the next turn starts fresh.

    Mirrors the sidecar layout (DS_HARNESS_SESSION_ROOT=<data>/harness-sessions,
    JSONL persistence under _no-cwd/<session id>). Nothing is deleted.
    """
    src = settings.data_dir / "harness-sessions" / "_no-cwd" / harness_session_id(project_id)
    if not src.is_dir():
        return False
    dest = settings.data_dir / "harness-sessions-archive" / f"{project_id}-{time.strftime('%Y%m%dT%H%M%S')}-{time.time_ns() % 10**9:09d}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    logger.warning("archived Harness session for %s to %s (%s)", project_id, dest, reason[:200])
    return True


def harness_session_id(project_id: str, nonce: str | None = None) -> str:
    """Stable execution identity; separate data roots never share a transcript."""
    payload = f"{settings.projects_dir.resolve().as_posix()}\n{project_id}"
    if nonce:
        payload += f"\n{nonce}"
    return hashlib.sha256(payload.encode()).hexdigest()


async def compact_harness_chat(*, project_id, chat_fn, history=None, on_progress=None,
                               context_capacity=None):
    if context_capacity is None:
        resolver = getattr(chat_fn, "resolve_context_capacity", None)
        context_capacity = await resolver() if resolver is not None else settings.director_num_ctx
    budget = harness_input_budget(context_capacity)
    seed = bounded_harness_history(history, budget)
    turn = BackendTurn(project_id, "", None, chat_fn, on_progress=on_progress, compact_only=True, history=seed)
    client = HarnessClient(settings.harness_base_url, settings.harness_internal_token,
                           timeout=settings.harness_turn_timeout_sec)
    body = {
        "message": "",
        "history": [],
        "session_id": harness_session_id(project_id),
        "operation": "compact",
        "context_window": budget,
        "max_steps": settings.harness_max_steps,
    }
    try:
        result = await client.run(body, turn.dispatch, on_progress)
    except HarnessError as exc:
        if exc.code != "COMPACTION_FAILED":
            raise
        transient = _compaction_failure_transient(exc)
        if not transient:
            archive_harness_session(project_id, reason=str(exc))
        body = {
            **body,
            "history": seed,
            "session_id": (harness_session_id(project_id, nonce=str(time.time_ns()))
                           if transient else harness_session_id(project_id)),
        }
        result = await client.run(body, turn.dispatch, on_progress)
    if not isinstance(result.get("compaction"), dict):
        raise ValueError("Harness did not confirm a compaction result; update/restart the sidecar")
    return result["compaction"]
