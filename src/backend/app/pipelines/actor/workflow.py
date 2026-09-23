"""ComfyUI graph fill for Qwen actor asset workbench.

Policy (simple workbench path):
- Optional **actor reference image** is fed into **master (人像)** and **full-body three-view**.
- One description text (no separate body/hair authority tracks).
- Three-view = workbench multipanel once (image1=master, image2=actor ref).
- Bust three-view = crop of the multipanel sheet (no second KSampler).
"""

from __future__ import annotations

import copy
import random
from typing import Any

from ...config import settings
from ...core.json_cache import load_json_file
from ...core.schemas import ComfyImageRef

# --- Inputs (user-facing) ---
NODE_DESCRIPTION = "58"  # Actor Description
NODE_BODY = "59"  # Body Description (optional)
NODE_HAIR = "60"  # Hairstyle description (optional, text authority)
NODE_ACTOR_IMAGE = "15"  # optional; blank 1x1 → text path
NODE_WARDROBE_IMAGE = "23"  # optional; blank 1x1 → keep original wardrobe
# Extra identity stills injected at fill time (not in the stock workbench JSON).
EXTRA_IMAGE_NODES = {
    "face": "80",
    "profile": "81",
    "back": "82",
    "threeview_extra": "83",
}
EXTRA_IMAGE_KEYS = ("face", "profile", "back", "threeview_extra")
NODE_WARDROBE_EXTRACT_PROMPT = "50"
NODE_NEGATIVE = "11"
NODE_REF_BASE_PROMPT = "63"  # actor ref → master base

# Auto switches are driven by image size (width > 1); do not set manually:
# 22 actor source, 30 wardrobe apply, 56 extract wardrobe

# Bust sampler chain removed at fill time (no secondary sampling)
SEED_NODES = ("13", "20", "28", "44", "54")  # no "37" bust sampler
BUST_SAMPLER_NODES = ("33", "34", "35", "36", "37", "38")

SAVE_NODES = {
    "57": "wardrobe_ref",
    "31": "master",
    "39": "bust_threeview",
    "46": "fullbody_threeview",
    "48": "asset_sheet",
}

OUTPUT_LABELS = {
    "wardrobe_ref": "00 · Wardrobe Reference",
    "master": "01 · Actor Master",
    "bust_threeview": "02 · Bust Three-view",
    "fullbody_threeview": "03 · Full-body Three-view",
    "asset_sheet": "04 · Asset Sheet",
}

# ComfyUI input folder placeholder (1×1). Presence routing: width > 1 ⇒ real upload.
BLANK_IMAGE = "qwen_actor_asset_blank.ppm"

# Baseline negative from working job 008126d9, minus "side view" (kills 3/4 panels)
# and without footwear bans — shoes vs bare feet come from user description / master text.
DEFAULT_NEGATIVE = (
    "cropped body, multiple people, duplicate body, extra limbs, missing limbs, "
    "deformed hands, malformed fingers, deformed feet, "
    "dramatic pose, text, watermark, collage, cluttered background, blur, "
    "inconsistent hairstyle across panels, wrong rear hairstyle, "
    "inventing a bun when hair is described as loose, converting loose hair to updo, "
    "invented clothing, studio wear on a nude body, covering a nude reference"
)

DEFAULT_DESCRIPTION = (
    "Photorealistic professional actor casting reference, one adult, "
    "front-facing complete full-body studio portrait, eye-level camera, "
    "standing upright in a neutral relaxed symmetrical pose, both arms naturally at sides, "
    "entire body visible head to toe, plain seamless white studio background, "
    "soft even lighting, exactly one person, no text, no collage. "
    "Specify age, face vibe, hair, outfit, footwear, and body build in this text."
)

# Node ids for three-view base prompts in qwen_actor_asset_workbench.api.json
NODE_FULLBODY_THREEVIEW_PROMPT = "66"
NODE_BUST_THREEVIEW_PROMPT = "68"  # unused when bust is crop-only; kept for compatibility

# Workbench multipanel three-view (nodes 40–45, prompts 66–67). Kept intact.
# Dynamic per-view node ids (200–281) are stripped if present so we never dual-run.
_DYNAMIC_PER_VIEW_IDS = tuple(str(i) for i in range(200, 282))

# Workbench full-body three-view canvas (3 equal panels)
_TV_SHEET_W = 2880
_TV_SHEET_H = 1920
_TV_BUST_H = 960

# Master base (ref path). User Description is appended at build time — it controls
# outfit/footwear when stated (e.g. bare feet vs shoes). Do not hardcode footwear here.
REF_ACTOR_MASTER_PROMPT = (
    "Image 1 is the actor REFERENCE photo. Preserve the same person: face identity, "
    "hairstyle, hair color/length, body build as visible, age and overall look. "
    "Normalize into a photorealistic professional actor casting master: front-facing complete "
    "full-body studio portrait, eye-level, upright symmetrical stance, arms at sides, "
    "head to toe with margin, plain seamless white studio background, soft even lighting. "
    "If the reference is a close-up face only, invent a natural full body consistent with that "
    "face and the written description (do not invent a different person). "
    "State of dress: follow the USER DESCRIPTION when it specifies clothing, lingerie, "
    "bare feet, or fully unclothed. Otherwise copy the exact dress state from image 1, "
    "including fully nude or barefoot when that is what the photo shows. "
    "Do not invent clothing, lingerie, towels, drapes, or studio wear. "
    "Exactly one person, no text, no collage, no props."
)

DRESS_UNCLOTHED = "unclothed"
DRESS_CLOTHED = "clothed"
DRESS_STATES = (DRESS_UNCLOTHED, DRESS_CLOTHED)

_DRESS_UNCLOTHED_PROMPT = (
    "DRESS STATE (mandatory): the actor is fully unclothed / nude. Bare skin only. "
    "No clothing, no lingerie, no bra, no panties, no towel, no sheet, no drape, "
    "no robe, no jacket, no studio wear. Keep the body uncovered in every panel."
)
_DRESS_CLOTHED_PROMPT = (
    "DRESS STATE (mandatory): the actor is clothed. Follow the wardrobe photo and/or "
    "USER DESCRIPTION for the outfit. Do not strip or undress the actor."
)
_DRESS_UNCLOTHED_NEGATIVE = (
    "clothing, clothes, outfit, lingerie, bra, panties, underwear, towel, drape, "
    "robe, dress, shirt, pants, jacket, studio wear, covered breasts, covered body"
)


def normalize_dress_state(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {DRESS_CLOTHED, "clothes", "clothed", "wardrobe", "dressed", "outfit"}:
        return DRESS_CLOTHED
    return DRESS_UNCLOTHED


def dress_state_prompt(dress_state: str | None) -> str:
    if normalize_dress_state(dress_state) == DRESS_CLOTHED:
        return _DRESS_CLOTHED_PROMPT
    return _DRESS_UNCLOTHED_PROMPT

_EXTRA_MASTER_PROMPT = (
    " Additional photos of the SAME person are provided as Image 2"
    "{and_image3} ({labels}). Fuse identity from every photo: face from close-ups, "
    "body and hair from full or back views. Do not invent a different person or average "
    "two people together."
)

_EXTRA_THREEVIEW_PROMPT = (
    " Image 3 is an extra identity view of the same person (back, profile, or face). "
    "Use it to lock the matching panel, especially the back view. Keep identity "
    "consistent with Image 1 and Image 2."
)

# Alias kept for older tests/imports
REF_FACE_ONLY_MASTER_PROMPT = REF_ACTOR_MASTER_PROMPT

# Three-view: multipanel (008126d9 baseline). Footwear follows master (no forced shoes).
_FULLBODY_THREEVIEW_PROMPT_TEMPLATE = (
    "Image 1 is the actor MASTER (full-body front). "
    "Image 2 is the original actor REFERENCE photo — keep the same person identity "
    "(face, hair, body vibe) consistent with image 1 and image 2. "
    "Create one wide professional actor turnaround sheet: exactly THREE equal vertical panels "
    "with clean white separators — and ONLY three figures total (one per panel). "
    "FORBIDDEN: more than three people, extra clones, a row of extra backs, six-panel grids, "
    "duplicated bodies, or extra mini-figures between panels. "
    "Every panel: complete body head to toe, upright neutral pose, arms at sides. "
    "Keep the same hairstyle, state of dress (including nude if the master is nude), "
    "body, and feet/footwear as the master across all panels. "
    "{headwear_instruction} "
    "LEFT: exact front view. CENTER: right-facing 45-degree three-quarter. "
    "RIGHT: exact back view. "
    "Same scale, eye-level, light-gray studio background, accurate hands and feet. "
    "No text, labels, crop, or clothing changes between panels."
)


def _fullbody_threeview_prompt(*, include_headwear: bool) -> str:
    headwear_instruction = (
        "The same hat or headwear visible on the master must appear in all three panels, "
        "with identical shape, color, trim, and placement"
        if include_headwear
        else "No hat or headwear in any panel"
    )
    return _FULLBODY_THREEVIEW_PROMPT_TEMPLATE.format(
        headwear_instruction=headwear_instruction
    )


FULLBODY_THREEVIEW_PROMPT = _fullbody_threeview_prompt(include_headwear=False)
BUST_THREEVIEW_PROMPT = (
    "Bust three-view is produced by cropping the full-body three-view (no second sample). "
    "Upper strip of the three panels: front | three-quarter | back head-and-shoulders."
)


def _strip_dynamic_per_view_nodes(prompt: dict[str, Any]) -> None:
    """Remove experimental per-view/hair-fix nodes if a graph was previously patched."""
    for nid in _DYNAMIC_PER_VIEW_IDS:
        prompt.pop(nid, None)


def _use_workbench_multipanel_threeview(
    prompt: dict[str, Any],
    *,
    include_headwear: bool,
    extra_image3_node: str | None = None,
) -> None:
    """
    Keep qwen_actor_asset_workbench multipanel three-view:
      encode 40 (image1=master 30, image2=actor ref 15, optional image3 extra)
      → sample → decode 45 → save 46
    Bust = crop 32 from 45; no second bust sampler.
    """
    _strip_dynamic_per_view_nodes(prompt)
    for nid in BUST_SAMPLER_NODES:
        prompt.pop(nid, None)

    threeview_prompt = _fullbody_threeview_prompt(include_headwear=include_headwear)
    if extra_image3_node:
        threeview_prompt = f"{threeview_prompt}{_EXTRA_THREEVIEW_PROMPT}"
    if NODE_FULLBODY_THREEVIEW_PROMPT in prompt:
        prompt[NODE_FULLBODY_THREEVIEW_PROMPT]["inputs"]["value"] = threeview_prompt
    if NODE_BUST_THREEVIEW_PROMPT in prompt:
        prompt[NODE_BUST_THREEVIEW_PROMPT]["inputs"]["value"] = BUST_THREEVIEW_PROMPT

    # Master + original reference into three-view; extra identity still as image3
    if "40" in prompt:
        prompt["40"]["inputs"]["image1"] = ["30", 0]
        prompt["40"]["inputs"]["image2"] = [NODE_ACTOR_IMAGE, 0]
        if extra_image3_node:
            prompt["40"]["inputs"]["image3"] = [extra_image3_node, 0]
        else:
            prompt["40"]["inputs"].pop("image3", None)
        if "67" in prompt:
            prompt["40"]["inputs"]["prompt"] = ["67", 0]

    if "46" in prompt:
        prompt["46"]["inputs"]["images"] = ["45", 0]

    if "32" in prompt:
        prompt["32"]["inputs"]["image"] = ["45", 0]
        prompt["32"]["inputs"]["width"] = _TV_SHEET_W
        prompt["32"]["inputs"]["height"] = _TV_BUST_H
        prompt["32"]["inputs"]["x"] = 0
        prompt["32"]["inputs"]["y"] = 0
    if "39" in prompt:
        prompt["39"]["inputs"]["images"] = ["32", 0]
        prompt["39"]["_meta"] = {
            **(prompt["39"].get("_meta") or {}),
            "title": "Save Bust Three-View (crop, no resample)",
        }
    if "47" in prompt:
        prompt["47"]["inputs"]["image_1"] = ["32", 0]
        prompt["47"]["inputs"]["image_2"] = ["45", 0]


WARDROBE_EXTRACT_PROMPT = (
    "Extract the complete coordinated outfit from the person in the source image and present it "
    "as a clean product-style wardrobe reference on a plain neutral background. Preserve garment "
    "silhouette, construction, layers, material, colors, trim, patterns, closures, and visible wear. "
    "Exclude the person's face, hair, body, pose, hands, jewelry, handheld objects, and background. "
    "{headwear} {footwear} Exactly one coordinated wardrobe set, no person, no text, no collage."
)


def _wardrobe_extract_prompt(
    *, include_headwear: bool, include_footwear: bool
) -> str:
    headwear = (
        "Include clearly visible hat or headwear as part of the coordinated look; preserve its exact "
        "type, silhouette, material, color, trim, and placement."
        if include_headwear
        else "Exclude headwear."
    )
    footwear = (
        "Include clearly visible shoes or boots as one matched pair; preserve their exact category, "
        "shape, color, material, sole, heel, closures, and distinctive wear."
        if include_footwear
        else "Exclude shoes and other footwear."
    )
    return WARDROBE_EXTRACT_PROMPT.format(headwear=headwear, footwear=footwear)


def _wardrobe_transfer_prompt(
    *, include_headwear: bool, include_footwear: bool
) -> str:
    headwear = (
        "Apply the hat or headwear from image 2, preserving its exact design and fit; keep the actor's "
        "identity and visible hair consistent around and beneath it."
        if include_headwear
        else "Preserve the master hairstyle and do not add headwear."
    )
    footwear = (
        "Apply the exact footwear from image 2 as a matched pair, preserving its design, "
        "material, and color."
        if include_footwear
        else "Preserve image 1's feet and footwear; if the master is barefoot, keep it "
        "barefoot, and if it wears shoes, keep equivalent shoes."
    )
    return (
        "Image 1 is the target actor master — LOCK its face, identity, body proportions, and pose. "
        "Image 2 is a wardrobe reference containing garments and only the explicitly selected "
        "wearable accessories. Image 3 is the original actor reference; use it for identity only, "
        "preserving the same facial features and distinctive identity. Do not copy clothing, pose, "
        "framing, or background from image 3. Re-dress image 1 with the garments from image 2. "
        f"{headwear} {footwear} Ignore the clothing model's face, hair, body, and pose. "
        "Exactly one front-facing complete full-body actor, plain white studio background, no text."
    )

WORKFLOW_FILENAME = "qwen_actor_asset_workbench.api.json"

LEAF_PREFIX = {
    "wardrobe_ref": "00_wardrobe_reference",
    "master": "01_actor_master",
    "bust_threeview": "02_bust_threeview",
    "fullbody_threeview": "03_fullbody_threeview",
    "asset_sheet": "04_actor_asset_sheet",
}


def load_base_prompt() -> dict[str, Any]:
    path = settings.workflows_dir / WORKFLOW_FILENAME
    if not path.exists():
        path = settings.workflow_path
    if not path.exists():
        raise FileNotFoundError(f"Workflow API JSON not found: {path}")
    return load_json_file(path)


def _inject_extra_identity_refs(
    prompt: dict[str, Any], extra_images: dict[str, str]
) -> str | None:
    """Load extra identity stills and wire them into master + three-view encodes.

    Qwen Edit Plus accepts three images. Master encode uses image1=primary actor
    plus up to two extras. Three-view encode uses image3 for a back/profile still.
    """
    extras = {
        key: extra_images[key]
        for key in EXTRA_IMAGE_KEYS
        if extra_images.get(key)
    }
    for key, nid in EXTRA_IMAGE_NODES.items():
        name = extras.get(key)
        if not name:
            prompt.pop(nid, None)
            continue
        prompt[nid] = {
            "class_type": "LoadImage",
            "inputs": {"image": name},
            "_meta": {"title": f"[INPUT] Extra {key.replace('_', ' ')}"},
        }

    if "16" in prompt:
        inputs = prompt["16"]["inputs"]
        inputs.pop("image2", None)
        inputs.pop("image3", None)
        for index, key in enumerate(list(extras)[:2]):
            inputs[f"image{index + 2}"] = [EXTRA_IMAGE_NODES[key], 0]

    for key in ("back", "profile", "threeview_extra", "face"):
        if extras.get(key):
            return EXTRA_IMAGE_NODES[key]
    return None


def build_actor_prompt(
    *,
    description: str = "",
    body_description: str = "",
    hair_description: str = "",
    negative_prompt: str = "",
    actor_image_name: str | None = None,
    wardrobe_image_name: str | None = None,
    extra_images: dict[str, str] | None = None,
    include_headwear: bool = False,
    include_footwear: bool = False,
    dress_state: str | None = None,
    seed: int | None = None,
    job_id: str | None = None,
) -> tuple[dict[str, Any], int]:
    """
    Patch workbench prompt.

    - No actor image → text-to-actor master
    - Actor image → ref into master (node 15→16) and into three-view (image2)
    - Extra identity photos → master image2/image3 and three-view image3
    - Single description text (legacy body/hair fields ignored / cleared)
    - Full-body three-view: workbench multipanel once
    - Bust three-view: crop of that sheet
    """
    prompt = copy.deepcopy(load_base_prompt())
    resolved_seed = seed if seed is not None else random.randint(0, 2**32 - 1)
    extras = {
        key: name
        for key, name in (extra_images or {}).items()
        if key in EXTRA_IMAGE_KEYS and name
    }

    # Single description — also injected into ref-path master (node 63), not only text path 58
    if not (dress_state or "").strip() and wardrobe_image_name:
        dress = DRESS_CLOTHED
    else:
        dress = normalize_dress_state(dress_state)
    if dress == DRESS_UNCLOTHED:
        wardrobe_image_name = None
    desc = (description or "").strip() or DEFAULT_DESCRIPTION
    desc = f"{dress_state_prompt(dress)}\n\n{desc}"
    prompt[NODE_DESCRIPTION]["inputs"]["value"] = desc
    prompt[NODE_BODY]["inputs"]["value"] = ""
    prompt[NODE_HAIR]["inputs"]["value"] = ""
    negative = negative_prompt or DEFAULT_NEGATIVE
    if dress == DRESS_UNCLOTHED and _DRESS_UNCLOTHED_NEGATIVE not in negative:
        negative = f"{negative}, {_DRESS_UNCLOTHED_NEGATIVE}"
    prompt[NODE_NEGATIVE]["inputs"]["text"] = negative

    # Master base + user description (outfit/footwear follow description when stated)
    extra_keys = [key for key in EXTRA_IMAGE_KEYS if extras.get(key)]
    master_prompt = REF_ACTOR_MASTER_PROMPT
    if extra_keys:
        master_prompt = (
            master_prompt
            + _EXTRA_MASTER_PROMPT.format(
                and_image3=" and Image 3" if len(extra_keys) > 1 else "",
                labels=", ".join(extra_keys),
            )
        )
    if NODE_REF_BASE_PROMPT in prompt:
        prompt[NODE_REF_BASE_PROMPT]["inputs"]["value"] = (
            f"{master_prompt}\n\nUSER DESCRIPTION:\n{desc}"
        )

    # Neutral concat delimiters (body/hair nodes empty; description already in 63)
    for nid in ("61", "62", "64", "65", "67", "69"):
        if nid in prompt:
            prompt[nid]["inputs"]["delimiter"] = "\n\n"

    if "24" in prompt:
        prompt["24"]["inputs"]["prompt"] = _wardrobe_transfer_prompt(
            include_headwear=include_headwear,
            include_footwear=include_footwear,
        )
        prompt["24"]["inputs"]["image3"] = [NODE_ACTOR_IMAGE, 0]
    if NODE_WARDROBE_EXTRACT_PROMPT in prompt:
        prompt[NODE_WARDROBE_EXTRACT_PROMPT]["inputs"]["prompt"] = (
            _wardrobe_extract_prompt(
                include_headwear=include_headwear,
                include_footwear=include_footwear,
            )
        )

    # Reference image → master path (15) and three-view image2 (same load node)
    prompt[NODE_ACTOR_IMAGE]["inputs"]["image"] = actor_image_name or BLANK_IMAGE
    prompt[NODE_WARDROBE_IMAGE]["inputs"]["image"] = wardrobe_image_name or BLANK_IMAGE

    # Ensure master ref encode uses actor image
    if "16" in prompt:
        prompt["16"]["inputs"]["image1"] = [NODE_ACTOR_IMAGE, 0]

    extra_image3 = _inject_extra_identity_refs(prompt, extras)

    _use_workbench_multipanel_threeview(
        prompt,
        include_headwear=include_headwear,
        extra_image3_node=extra_image3,
    )
    if NODE_FULLBODY_THREEVIEW_PROMPT in prompt:
        prompt[NODE_FULLBODY_THREEVIEW_PROMPT]["inputs"]["value"] = (
            f"{prompt[NODE_FULLBODY_THREEVIEW_PROMPT]['inputs']['value']} {dress_state_prompt(dress)}"
        )

    for nid in SEED_NODES:
        if nid in prompt:
            prompt[nid]["inputs"]["seed"] = resolved_seed

    if job_id:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)[:32]
        for nid, key in SAVE_NODES.items():
            if nid in prompt:
                prompt[nid]["inputs"]["filename_prefix"] = (
                    f"director-studio/{safe}/{LEAF_PREFIX.get(key, key)}"
                )

    return prompt, resolved_seed


def map_history_outputs(history: dict[str, Any]) -> dict[str, ComfyImageRef]:
    outputs = history.get("outputs") or {}
    mapped: dict[str, ComfyImageRef] = {}
    for nid, key in SAVE_NODES.items():
        node_out = outputs.get(nid) or outputs.get(str(nid))
        if not node_out:
            continue
        images = node_out.get("images") or []
        if not images:
            continue
        img = images[-1]
        mapped[key] = ComfyImageRef(
            filename=img.get("filename") or "",
            subfolder=img.get("subfolder") or "",
            type=img.get("type") or "output",
        )
    return mapped


def derive_mode(*, has_actor_ref: bool, has_wardrobe_ref: bool) -> str:
    """Display helper only — not sent to Comfy switches."""
    if has_wardrobe_ref:
        return "wardrobe"
    if has_actor_ref:
        return "reference"
    return "text"
