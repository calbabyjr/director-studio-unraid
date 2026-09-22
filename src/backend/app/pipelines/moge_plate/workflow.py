"""Tiny Comfy graph: scene plate → MoGe depth + normal maps for Qwen extras."""

from __future__ import annotations

import copy
from typing import Any

from ...core.schemas import ComfyImageRef

NODE_LOAD = "1"
NODE_MODEL = "2"
NODE_INFER = "3"
NODE_DEPTH = "4"
NODE_NORMAL = "5"
NODE_SAVE_DEPTH = "6"
NODE_SAVE_NORMAL = "7"

OUTPUT_LABELS = {
    "moge_orbit": "MoGe depth",
    "moge_back": "MoGe normals",
}


def build_moge_plate_graph(image_name: str, *, job_id: str | None = None) -> dict[str, Any]:
    prefix = "director-studio/moge"
    if job_id:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_id)[:32]
        prefix = f"director-studio/{safe}/moge"
    return {
        NODE_LOAD: {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
            "_meta": {"title": "Scene plate"},
        },
        NODE_MODEL: {
            "class_type": "LoadMoGeModel",
            "inputs": {"model_name": "moge_2_vitl_normal_fp16.safetensors"},
        },
        NODE_INFER: {
            "class_type": "MoGeInference",
            "inputs": {
                "moge_model": [NODE_MODEL, 0],
                "image": [NODE_LOAD, 0],
                "resolution_level": 6,
                "fov_x_degrees": 0.0,
                "batch_size": 1,
                "force_projection": True,
                "apply_mask": True,
            },
        },
        NODE_DEPTH: {
            "class_type": "MoGeRender",
            "inputs": {"moge_geometry": [NODE_INFER, 0], "output": "depth_colored"},
        },
        NODE_NORMAL: {
            "class_type": "MoGeRender",
            "inputs": {"moge_geometry": [NODE_INFER, 0], "output": "normal_opengl"},
        },
        NODE_SAVE_DEPTH: {
            "class_type": "SaveImage",
            "inputs": {"images": [NODE_DEPTH, 0], "filename_prefix": f"{prefix}_depth"},
        },
        NODE_SAVE_NORMAL: {
            "class_type": "SaveImage",
            "inputs": {"images": [NODE_NORMAL, 0], "filename_prefix": f"{prefix}_normal"},
        },
    }


def map_history_outputs(history: dict[str, Any]) -> dict[str, ComfyImageRef]:
    outputs = history.get("outputs") or {}
    mapped: dict[str, ComfyImageRef] = {}
    pairing = ((NODE_SAVE_DEPTH, "moge_orbit"), (NODE_SAVE_NORMAL, "moge_back"))
    for nid, key in pairing:
        node_out = outputs.get(nid) or {}
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


def load_base_prompt() -> dict[str, Any]:
    return copy.deepcopy(build_moge_plate_graph("placeholder.png"))
