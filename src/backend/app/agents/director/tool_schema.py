"""Director native-tool contracts and per-turn availability policy."""

from __future__ import annotations

import re
from typing import Any, Iterable

from ...config import settings
from ...core.projects.models import AssetCoverageReviewSubmission, Project
from .stage_guides import craft_guides_for_message
from .intent import (
    actor_design_intent,
    ask_choices_intent,
    assemble_sequence_intent,
    draft_screenplay_intent,
    explicit_gpt_image_intent,
    explicit_h3_generation_intent,
    explicit_layout_generation_intent,
    lock_script_intent,
    material_review_target_shot_id,
    prop_design_intent,
    sequence_review_intent,
    tail_frame_extraction_intent,
)
from .planner import (
    AppendShotSubmission,
    ShotRefsPatchSubmission,
    ShotRevisionSubmission,
    ShotSceneRefSelection,
    StoryboardSubmission,
)


IMAGE_TOOLS = frozenset(
    {
        "queue_ref_frame",
        "queue_gpt_ref_frame",
        "ref_frame",
        "extract_clip_tail_frame",
        "accept_ref_frame",
        "revise_ref_frame",
        "approve_layout",
        "approve",
        "reject_layout",
        "reject",
        "write_prompt",
    }
)
PLAN_TOOLS = frozenset({"plan_shots", "plan"})
STORYBOARD_TOOLS = frozenset({"save_storyboard"})
SCRIPT_TOOLS = frozenset({"set_script"})
SCRIPT_DRAFT_TOOLS = frozenset({"draft_screenplay"})
SCRIPT_LOCK_TOOLS = frozenset({"lock_script"})


def function_tool(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def _material_review_tool(name: str, target_shot_id: str) -> dict[str, Any]:
    source = next(
        tool
        for tool in DIRECTOR_TOOL_SCHEMAS
        if tool["function"]["name"] == name
    )
    parameters = source["function"]["parameters"]
    properties = dict(parameters.get("properties") or {})
    required = list(parameters.get("required") or [])
    target_key = "target_shot_id" if name == "extract_clip_tail_frame" else "shot_id"
    if name in {"queue_ref_frame", "write_prompt"}:
        for selector in ("shot_index", "title", "all"):
            properties.pop(selector, None)
    properties[target_key] = {
        "type": "string",
        "const": target_shot_id,
        "description": "Exact Shot changed in the material editor",
    }
    if target_key not in required:
        required.append(target_key)
    return function_tool(
        name,
        source["function"]["description"],
        properties,
        required=required,
    )


SHOT_SELECTOR = {
    "shot_id": {"type": "string", "description": "Exact shot id"},
    "shot_index": {"type": "integer", "minimum": 1},
    "title": {"type": "string", "description": "Shot title"},
    "all": {"type": "boolean", "default": False},
}
LAYOUT_SOURCE_REF_ITEM = {
    "type": "object",
    "properties": {
        "role": {
            "type": "string",
            "enum": [
                "layout_ref_frame",
                "actor",
                "costume",
                "scene",
                "prop",
                "other",
            ],
        },
        "asset_id": {"type": "string", "minLength": 1},
        "file_key": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["role", "asset_id"],
}

LAYOUT_ACTIVATION_MODE = {
    "type": "string",
    "enum": ["replace", "append"],
    "default": "replace",
    "description": (
        "replace regenerates the active composition set; append keeps "
        "existing active Layouts and adds a compatible state."
    ),
}

GPT_REF_FRAME_TOOL = function_tool(
    "queue_gpt_ref_frame",
    (
        "Generate one Layout through the optional local ChatGPT Bridge only "
        "after the user explicitly requests GPT/ChatGPT image generation. "
        "Preserve ordered real inventory sources and assign every ImageN one job. "
        "An Actor source is an authoritative identity reference, not a loose style "
        "hint: preserve exact facial structure, hair, body proportions, and its "
        "approved wardrobe unless an attached Costume source or explicit user "
        "request changes clothing. Use exact file_keys; prefer bust_threeview for "
        "face fidelity and a full-body/master source for wardrobe when both jobs "
        "matter and reference capacity allows. "
        "When no useful source asset exists, use an empty source_refs array for "
        "prompt-only generation and do not mention ImageN."
    ),
    {
        "shot_id": {"type": "string", "minLength": 1},
        "purpose": {"type": "string", "minLength": 1},
        "state_description": {"type": "string", "minLength": 1},
        "time_hint": {"type": "string"},
        "activation_mode": LAYOUT_ACTIVATION_MODE,
        "source_refs": {
            "type": "array",
            "items": LAYOUT_SOURCE_REF_ITEM,
        },
        "generation_prompt": {"type": "string", "minLength": 1},
    },
    required=[
        "shot_id",
        "purpose",
        "state_description",
        "source_refs",
        "generation_prompt",
    ],
)

ACTOR_DESIGN_TOOL = function_tool(
    "queue_actor_design",
    (
        "Generate one reviewable character design. Local is the default provider; "
        "use GPT only when the user explicitly asks for GPT or ChatGPT generation. "
        "Do not save it to the Actor library until the user accepts it."
    ),
    {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "body_description": {"type": "string"},
        "hair_description": {"type": "string"},
        "wardrobe_description": {"type": "string"},
        "provider": {
            "type": "string",
            "enum": ["gpt", "local"],
            "default": "local",
        },
        "generation_prompt": {"type": "string", "minLength": 1},
    },
    required=["name", "description", "generation_prompt"],
)

PROP_DESIGN_TOOL = function_tool(
    "queue_prop_design",
    (
        "Generate one reviewable standalone prop reference sheet from a source "
        "photo (library asset or current chat upload). Use this for objects, "
        "furniture, weapons, and wardrobe pieces — never queue_actor_design. "
        "Do not save it to the Prop library until the user accepts it."
    ),
    {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "generation_prompt": {"type": "string", "minLength": 1},
        "source_asset_id": {
            "type": "string",
            "description": "Library asset that contains the object (scene still, photo, or existing prop).",
        },
        "file_key": {
            "type": "string",
            "description": "Optional exact file key on source_asset_id (e.g. master, angle_00).",
        },
        "image_index": {
            "type": "integer",
            "minimum": 1,
            "maximum": 4,
            "description": "One-based Image number from the current user upload, if extracting from chat.",
        },
    },
    required=["name", "description", "generation_prompt"],
)

PROP_ACCEPT_TOOL = function_tool(
    "accept_prop_design",
    "Save one succeeded Prop design job after explicit user acceptance.",
    {
        "job_id": {"type": "string", "minLength": 1},
        "name": {"type": "string"},
        "notes": {"type": "string"},
    },
    required=["job_id"],
)

ACTOR_ACCEPT_TOOL = function_tool(
    "accept_actor_design",
    "Save one succeeded Actor design job after explicit user acceptance.",
    {
        "job_id": {"type": "string", "minLength": 1},
        "name": {"type": "string"},
        "notes": {"type": "string"},
    },
    required=["job_id"],
)

CHAT_IMAGE_CLASSIFICATION_TOOL = function_tool(
    "classify_chat_image",
    (
        "Classify one user-uploaded chat image from its visible contents and the "
        "current user message, give it a concise useful name and factual notes, "
        "then import it into the current project's Library when confidence is "
        "sufficient. Use chat_only when the image is too ambiguous."
    ),
    {
        "image_index": {
            "type": "integer",
            "minimum": 1,
            "maximum": 4,
            "description": "One-based Image number from the current user upload.",
        },
        "kind": {
            "type": "string",
            "enum": [
                "actors",
                "costumes",
                "scenes",
                "props",
                "layouts",
                "chat_only",
            ],
        },
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 120,
            "description": "Concise human-readable asset name in the user's language.",
        },
        "notes": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
            "description": (
                "Factual visible appearance and intended production use; do not "
                "invent details that are not visible or stated by the user."
            ),
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
    },
    required=["image_index", "kind", "name", "notes", "confidence"],
)

ASK_CHOICES_TOOL = function_tool(
    "ask_choices",
    (
        "Ask the user one or more multiple-choice questions as checkboxes. "
        "Use this instead of writing a quiz in prose when they can pick from options. "
        "Wait for their reply; do not assume answers."
    ),
    {
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "prompt": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 400,
                        "description": "The question shown above the checkboxes.",
                    },
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 8,
                        "items": {"type": "string", "minLength": 1, "maxLength": 160},
                    },
                    "allow_multiple": {
                        "type": "boolean",
                        "description": "True if they may tick more than one box.",
                    },
                },
                "required": ["prompt", "options"],
            },
        }
    },
    required=["questions"],
)

DIRECTOR_TOOL_SCHEMAS: list[dict[str, Any]] = [
    ASK_CHOICES_TOOL,
    ACTOR_DESIGN_TOOL,
    ACTOR_ACCEPT_TOOL,
    PROP_DESIGN_TOOL,
    PROP_ACCEPT_TOOL,
    function_tool(
        "set_script",
        "Save finished screenplay pages the user supplied as-is. Do not use this to expand a premise.",
        {"script": {"type": "string", "minLength": 1}},
        required=["script"],
    ),
    function_tool(
        "draft_screenplay",
        (
            "Author a Fountain screenplay from a premise, notes, or source story: "
            "scene headings, action, and spoken lines. Save it as an unlocked draft "
            "and stop. Do not plan shots, cast, or generate video in the same turn."
        ),
        {
            "premise": {
                "type": "string",
                "description": "The user's idea, logline, or brief.",
            },
            "notes": {
                "type": "string",
                "description": "Optional constraints: tone, characters, length, adult/NSFW, setting.",
            },
            "source_excerpt": {
                "type": "string",
                "description": "Optional pasted or uploaded story to adapt, not a whole novel.",
            },
            "script": {
                "type": "string",
                "minLength": 1,
                "description": "The authored Fountain screenplay to save as the draft.",
            },
        },
        required=["script"],
    ),
    function_tool(
        "lock_script",
        (
            "Lock the current screenplay as the source of truth after the user "
            "explicitly approves the draft. Shot planning may follow on a later turn."
        ),
    ),
    {
        "type": "function",
        "function": {
            "name": "review_asset_coverage",
            "description": (
                "Persist an advisory review of whether the current assets and their "
                "file_keys cover the screenplay. Recommend useful additions, or record "
                "that the user chose to skip. This never blocks storyboarding."
            ),
            "parameters": AssetCoverageReviewSubmission.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_storyboard",
            "description": (
                "Persist the exact complete ordered storyboard you authored for the "
                "current screenplay. Use PROJECT_STATE.script_hash. Preserve every "
                "existing Shot's PROJECT_STATE id in shot_id, and omit shot_id only "
                "for a genuinely new Shot. For adding one Shot at the end, use append_shot instead."
            ),
            "parameters": StoryboardSubmission.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_shot",
            "description": (
                "Append exactly one new Shot at the end. Submit only the new shot's "
                "authored fields, not existing Shots or production state. Python assigns "
                "its ID and preserves every existing Shot, ref, prompt, Layout and video link. "
                "Copy PROJECT_STATE.script_hash and last_shot_id for stale/replay checks."
            ),
            "parameters": AppendShotSubmission.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revise_shot",
            "description": (
                "Update only explicitly supplied authored fields on exactly one "
                "existing Shot. Preserves neighboring Shots, Picture and voice refs, "
                "Layouts, and historical jobs while invalidating that Shot's stale "
                "prompt and active H3 link."
            ),
            "parameters": ShotRevisionSubmission.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_shot_refs",
            "description": (
                "Replace only the complete ordered Picture bindings on named "
                "existing shots. Use for exact asset additions or recasting without "
                "changing story beats, dialogue, duration, title, or shot order."
            ),
            "parameters": ShotRefsPatchSubmission.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_shot_scene_ref",
            "description": (
                "Apply a human's exact scene asset and file_key selection to one "
                "existing shot while preserving every other Picture binding and "
                "all story fields. The file_key is authoritative: do not reinterpret "
                "camera direction or replace it from filename angle tokens."
            ),
            "parameters": ShotSceneRefSelection.model_json_schema(),
        },
    },
    function_tool("plan_shots", "Plan shots from the current screenplay."),
    function_tool(
        "queue_ref_frame",
        (
            "Generate or regenerate a Layout reference frame for selected shots. "
            "For an additional Layout, use only after discussion establishes a "
            "distinct visual purpose, and set activation_mode=append only when "
            "the user explicitly wants to preserve existing active Layouts. "
            "Provide an explicit continuity brief and "
            "1–3 exact source assets from the inventory so the downstream Qwen "
            "prompt can assign each image a clear visual job."
        ),
        {
            **SHOT_SELECTOR,
            "force": {"type": "boolean", "default": False},
            "purpose": {
                "type": "string",
                "description": "Why this Layout is needed for the shot.",
            },
            "state_description": {
                "type": "string",
                "description": "The exact story or continuity state shown.",
            },
            "time_hint": {
                "type": "string",
                "description": "Optional script or shot timing hint.",
            },
            "activation_mode": LAYOUT_ACTIVATION_MODE,
            "source_refs": {
                "type": "array",
                "maxItems": 3,
                "items": LAYOUT_SOURCE_REF_ITEM,
            },
        },
    ),
    function_tool(
        "extract_clip_tail_frame",
        (
            "Extract the last decoded frame of a succeeded H3 clip into a "
            "pending, unselected Layout on a later shot. Use exact shot IDs. "
            "Clarify rather than guess when the source clip is ambiguous. "
            "Do not visually approve the image."
        ),
        {
            "source_shot_id": {
                "type": "string",
                "minLength": 1,
                "description": "Exact source shot id whose H3 clip is extracted.",
            },
            "target_shot_id": {
                "type": "string",
                "minLength": 1,
                "description": "Exact target shot id that receives the Layout.",
            },
            "source_version": {
                "type": "string",
                "description": "latest, or a generation number such as v2 or 2.",
            },
            "source_job_id": {
                "type": "string",
                "description": "Exact H3 job id when the user named one.",
            },
            "output_kind": {
                "type": "string",
                "enum": ["enhanced", "raw"],
                "description": "Which materialized video output to decode.",
            },
        },
        required=["source_shot_id", "target_shot_id"],
    ),
    function_tool(
        "accept_ref_frame",
        (
            "Record acceptance from this Director conversation on one existing "
            "Layout and select that exact Layout for the H3 Picture pack."
        ),
        {
            **SHOT_SELECTOR,
            "layout_ref_id": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "LayoutReference id (lref_…) or Layout library asset id "
                    "(lay_…) the user accepted."
                ),
            },
            "feedback": {
                "type": "string",
                "description": "Optional concise reason the Layout is usable.",
            },
        },
        required=["layout_ref_id"],
    ),
    function_tool(
        "revise_ref_frame",
        (
            "Record feedback from this Director conversation on one existing "
            "Layout and generate a linked replacement. Use this instead of "
            "queue_ref_frame when the user critiques a generated reference. "
            "For a clip_tail_frame origin, additional_source_refs (max 2) are "
            "honored; the extracted Layout is always Qwen Image1."
        ),
        {
            **SHOT_SELECTOR,
            "layout_ref_id": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "LayoutReference id (lref_…) or Layout library asset id "
                    "(lay_…) being critiqued."
                ),
            },
            "feedback": {
                "type": "string",
                "minLength": 1,
                "description": "Concise actionable summary of the user's feedback.",
            },
            "additional_source_refs": {
                "type": "array",
                "maxItems": 2,
                "description": (
                    "Optional extra Qwen sources for a clip_tail_frame redraw. "
                    "Ignored for ordinary generated Layouts."
                ),
                "items": LAYOUT_SOURCE_REF_ITEM,
            },
        },
        required=["layout_ref_id", "feedback"],
    ),
    function_tool(
        "write_prompt",
        "Prepare the six-section H3 production prompt for one shot. The backend ensures visual evidence "
        "for every current Picture, reviewing new or changed references first, decides whether the Creative brief "
        "and prompt need changes, and preserves old drafts if review is incomplete or needs a user choice.",
        dict(SHOT_SELECTOR),
    ),
    function_tool(
        "remember_note",
        (
            "Save a durable standing note that survives new chat sessions and "
            "the short recent-chat window. Use for lasting user rules such as "
            "setting, casting, wardrobe, or 'never do X'. Do not store one-off "
            "shot feedback."
        ),
        {
            "text": {
                "type": "string",
                "minLength": 8,
                "maxLength": 240,
                "description": "One concise standing rule in the user's language.",
            },
            "scope": {
                "type": "string",
                "enum": ["project", "global"],
                "description": "project = this film only; global = every project.",
            },
        },
        required=["text"],
    ),
    function_tool(
        "improve_soul",
        (
            "Append a lasting craft lesson to the active Director soul so future "
            "projects using this soul inherit it. Use after the user confirms a "
            "durable directing rule, not for one-off shot notes."
        ),
        {
            "text": {
                "type": "string",
                "minLength": 8,
                "maxLength": 240,
                "description": "One concise lesson in the user's language.",
            },
        },
        required=["text"],
    ),
    function_tool(
        "forget_note",
        "Delete one standing note by id or by a unique snippet of its text.",
        {
            "note_id": {
                "type": "string",
                "description": "Standing note id (mem_…) or a unique text snippet.",
            },
            "text": {
                "type": "string",
                "description": "Unique snippet of the note to forget if id is unknown.",
            },
        },
    ),
    function_tool(
        "inspect_asset",
        "Read one exact Library image before casting or answering visual questions, even with no Shots. "
        "Returns visual observations, metadata conflicts and content hash, not image bytes. "
        "Use when appearance is unknown or names/descriptions may be misleading; does not change the asset or project.",
        {"asset_id": {"type": "string", "minLength": 1}, "file_key": {"type": "string", "minLength": 1}},
        required=["asset_id", "file_key"],
    ),
    function_tool(
        "get_status",
        "Read project status, or the full saved details of one Shot by exact shot_id before editing it.",
        {"shot_id": {"type": "string", "description": "Optional exact Shot ID to read; omit for project status."}},
    ),
    function_tool(
        "queue_h3",
        "Queue local H3 Ref2AV video for one Shot or every submittable Shot. "
        "Requires Picture refs and a complete six-section prompt. Returns a job_ id. "
        "Use when the user asks to generate, queue, or render H3 clips.",
        dict(SHOT_SELECTOR),
    ),
    function_tool(
        "review_sequence",
        (
            "Read the current storyboard as a cut: planned runtime, which Shots have "
            "succeeded H3 clips, and continuity issues such as missing Voice on "
            "dialogue, left/right axis jumps, Scene/Actor mismatches, and missing "
            "tail-frame handoffs. Does not generate media."
        ),
    ),
    function_tool(
        "assemble_sequence",
        (
            "Concatenate succeeded H3 clips in storyboard order into a rough-cut "
            "MP4 and sidecar SRT. Skip Shots that have no usable clip. Use only "
            "when the user asks to assemble, stitch, or export a watchable cut."
        ),
    ),
]


def director_tool_schemas(
    project: Project,
    *,
    current_message: str = "",
    allow_save_storyboard: bool = True,
    include_chat_image_import: bool = False,
) -> list[dict[str, Any]]:
    if include_chat_image_import:
        return [CHAT_IMAGE_CLASSIFICATION_TOOL]
    if ask_choices_intent(current_message):
        return [ASK_CHOICES_TOOL]
    if draft_screenplay_intent(current_message) and not project.script_locked:
        return [
            tool
            for tool in DIRECTOR_TOOL_SCHEMAS
            if tool["function"]["name"] == "draft_screenplay"
        ]
    if (
        lock_script_intent(current_message)
        and (project.script_text or "").strip()
        and not project.script_locked
    ):
        return [
            tool
            for tool in DIRECTOR_TOOL_SCHEMAS
            if tool["function"]["name"] in {"lock_script", "set_script", "get_status"}
        ]
    if actor_design_intent(current_message) and prop_design_intent(current_message):
        return [ACTOR_DESIGN_TOOL, PROP_DESIGN_TOOL]
    if actor_design_intent(current_message):
        return [ACTOR_DESIGN_TOOL]
    if prop_design_intent(current_message):
        return [PROP_DESIGN_TOOL]
    if explicit_h3_generation_intent(current_message):
        return [
            tool
            for tool in DIRECTOR_TOOL_SCHEMAS
            if tool["function"]["name"] in {"queue_h3", "get_status"}
        ]
    layout_generation_authorized = explicit_layout_generation_intent(
        current_message
    )
    material_review_target = material_review_target_shot_id(current_message)
    if material_review_target:
        tools = [_material_review_tool("write_prompt", material_review_target)]
        if layout_generation_authorized:
            tools.append(
                _material_review_tool("queue_ref_frame", material_review_target)
            )
        if tail_frame_extraction_intent(current_message):
            tools.append(
                _material_review_tool(
                    "extract_clip_tail_frame",
                    material_review_target,
                )
            )
        return tools
    excluded = set()
    if project.script_locked:
        excluded.update(SCRIPT_TOOLS)
        excluded.update(SCRIPT_DRAFT_TOOLS)
        excluded.update(SCRIPT_LOCK_TOOLS)
    draft_gate = bool(
        project.script_draft_pending or not (project.script_text or "").strip()
    )
    if draft_gate:
        excluded.update(PLAN_TOOLS)
        excluded.update(STORYBOARD_TOOLS)
        excluded.update(IMAGE_TOOLS)
        excluded.update(
            {
                "queue_h3",
                "assemble_sequence",
                "review_sequence",
                "append_shot",
                "queue_actor_design",
                "accept_actor_design",
                "queue_prop_design",
                "accept_prop_design",
            }
        )
    if not project.script_draft_pending or not (project.script_text or "").strip():
        excluded.update(SCRIPT_LOCK_TOOLS)
    if not allow_save_storyboard:
        excluded.update(STORYBOARD_TOOLS)
    if not layout_generation_authorized:
        excluded.update({"queue_ref_frame", "revise_ref_frame"})
    if not tail_frame_extraction_intent(current_message):
        excluded.add("extract_clip_tail_frame")
    if not assemble_sequence_intent(current_message):
        excluded.add("assemble_sequence")
    tools = [
        tool
        for tool in DIRECTOR_TOOL_SCHEMAS
        if tool["function"]["name"] not in excluded
    ]
    normalized = current_message.lower()
    shot_layout_turn = bool(
        re.search(r"(?:shot\s*\d+|第\s*\d+\s*镜)", normalized)
        and re.search(
            r"(?:layout|reference(?:\s+frame)?|refs?\b|materials?\b|assets?\b|"
            r"composition|构图|参考帧|首帧|素材|绑定|h3\b|prompt\b)",
            normalized,
        )
    )
    if shot_layout_turn:
        relevant = {
            "append_shot",
            "revise_shot",
            "patch_shot_refs",
            "set_shot_scene_ref",
            "queue_ref_frame",
            "extract_clip_tail_frame",
            "accept_ref_frame",
            "revise_ref_frame",
            "write_prompt",
            "queue_h3",
            "get_status",
            "inspect_asset",
            "ask_choices",
            "remember_note",
            "forget_note",
            "improve_soul",
            "review_sequence",
        }
        tools = [
            tool
            for tool in tools
            if tool["function"]["name"] in relevant
        ]
    if settings.gpt_bridge_configured and layout_generation_authorized:
        tools.append(GPT_REF_FRAME_TOOL)
    return tools


def director_chat_guides(
    project: Project,
    *,
    include_visual_qc: bool,
    current_message: str = "",
) -> tuple[str, ...]:
    guides: list[str] = []
    if project.script_locked:
        guides.append("script-planning")
    if explicit_gpt_image_intent(current_message) and not actor_design_intent(
        current_message
    ):
        guides.append("reference-frame-generation")
    if include_visual_qc:
        guides.append("visual-qc")
    if sequence_review_intent(current_message):
        guides.append("sequence-assembly")
    guides.extend(craft_guides_for_message(current_message))
    return tuple(guides)


def offered_tool_names(
    tool_schemas: Iterable[dict[str, Any]],
) -> frozenset[str]:
    return frozenset(
        str(tool.get("function", {}).get("name") or "").strip()
        for tool in tool_schemas
        if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
    )
