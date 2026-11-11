"""ComfyUI graph for Wan 2.2 image-to-video from one layout still."""

from __future__ import annotations

import random
from typing import Any

from ...core.schemas import ComfyImageRef

OUTPUT_LABELS = {"video": "Wan video"}
# Official quality negative. It does not suppress adult content.
NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，"
    "整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，"
    "画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
    "静止不动的画面，杂乱的背景，三条腿，倒着走"
)
MAX_SEED = 2**32 - 1


def build_graph(
    *,
    prompt: str,
    image_name: str,
    high_unet: str,
    low_unet: str,
    clip_name: str,
    vae_name: str,
    seed: int | None = None,
    width: int = 832,
    height: int = 480,
    length: int = 81,
    filename_prefix: str = "wan-director-studio/clip",
) -> tuple[dict[str, Any], int]:
    """Two-stage 14B I2V graph. The layout image is the opening frame."""
    resolved = int(seed if seed is not None else random.randrange(1, MAX_SEED))
    graph: dict[str, Any] = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": high_unet, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": low_unet, "weight_dtype": "default"},
        },
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": clip_name, "type": "wan", "device": "default"},
        },
        "4": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": vae_name},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["3", 0]},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": NEGATIVE, "clip": ["3", 0]},
        },
        "7": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        },
        "8": {
            "class_type": "WanImageToVideo",
            "inputs": {
                "positive": ["5", 0],
                "negative": ["6", 0],
                "vae": ["4", 0],
                "width": width,
                "height": height,
                "length": length,
                "batch_size": 1,
                "start_image": ["7", 0],
            },
        },
        "9": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"model": ["1", 0], "shift": 8.0},
        },
        "10": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"model": ["2", 0], "shift": 8.0},
        },
        "11": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "add_noise": "enable",
                "noise_seed": resolved,
                "steps": 20,
                "cfg": 3.5,
                "sampler_name": "euler",
                "scheduler": "simple",
                "start_at_step": 0,
                "end_at_step": 10,
                "return_with_leftover_noise": "enable",
                "model": ["9", 0],
                "positive": ["8", 0],
                "negative": ["8", 1],
                "latent_image": ["8", 2],
            },
        },
        "12": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "add_noise": "disable",
                "noise_seed": resolved,
                "steps": 20,
                "cfg": 3.5,
                "sampler_name": "euler",
                "scheduler": "simple",
                "start_at_step": 10,
                "end_at_step": 10000,
                "return_with_leftover_noise": "disable",
                "model": ["10", 0],
                "positive": ["8", 0],
                "negative": ["8", 1],
                "latent_image": ["11", 0],
            },
        },
        "13": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["12", 0], "vae": ["4", 0]},
        },
        "14": {
            "class_type": "CreateVideo",
            "inputs": {"images": ["13", 0], "fps": 16.0},
        },
        "15": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["14", 0],
                "filename_prefix": filename_prefix,
                "format": "auto",
                "codec": "auto",
            },
        },
    }
    return graph, resolved


def map_history_outputs(history: dict[str, Any]) -> dict[str, ComfyImageRef]:
    outputs = history.get("outputs") if isinstance(history, dict) else None
    if not isinstance(outputs, dict):
        return {}
    for node in outputs.values():
        if not isinstance(node, dict):
            continue
        for field in ("videos", "gifs", "images"):
            items = node.get(field)
            if not isinstance(items, list):
                continue
            for media in items:
                if not isinstance(media, dict):
                    continue
                filename = str(media.get("filename") or "")
                if not filename.lower().endswith((".mp4", ".webm", ".mov", ".mkv")):
                    continue
                return {
                    "video": ComfyImageRef(
                        filename=filename,
                        subfolder=media.get("subfolder") or "",
                        type=media.get("type") or "output",
                    )
                }
    return {}
