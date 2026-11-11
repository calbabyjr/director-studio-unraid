"""Animate one layout still with local Wan 2.2."""

from __future__ import annotations

from typing import Any, Literal

from ...config import settings
from ...core.schemas import ComfyImageRef, JobRecord
from ..base import Pipeline
from . import workflow


class WanI2VPipeline(Pipeline):
    id = "wan_i2v"
    asset_kind = "productions"
    display_name = "Wan 2.2 image-to-video"
    description = (
        "Animates the shot's layout still with a local Wan 2.2 image-to-video model."
    )
    generation_kind: Literal["image", "video"] = "video"

    @property
    def output_labels(self) -> dict[str, str]:
        return dict(workflow.OUTPUT_LABELS)

    def build_prompt(
        self,
        job: JobRecord,
        *,
        uploaded_images: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        image_name = uploaded_images.get("layout")
        if not image_name:
            raise ValueError("Wan needs the layout still")
        params = job.params or {}
        prompt = str(params.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Wan needs the shot action")
        return workflow.build_graph(
            prompt=prompt,
            image_name=image_name,
            high_unet=str(params.get("wan_high_unet") or settings.wan_high_unet),
            low_unet=str(params.get("wan_low_unet") or settings.wan_low_unet),
            clip_name=str(params.get("wan_clip") or settings.wan_clip),
            vae_name=str(params.get("wan_vae") or settings.wan_vae),
            seed=job.seed,
            width=int(params.get("width") or 832),
            height=int(params.get("height") or 480),
            length=int(params.get("frames") or 81),
            filename_prefix=str(
                params.get("output_prefix") or f"wan-director-studio/{job.id}"
            ),
        )

    def map_history_outputs(
        self,
        history: dict[str, Any],
        *,
        job: JobRecord | None = None,
    ) -> dict[str, ComfyImageRef]:
        del job
        return workflow.map_history_outputs(history)

    def library_input_keys(self) -> list[str]:
        return ["layout"]
