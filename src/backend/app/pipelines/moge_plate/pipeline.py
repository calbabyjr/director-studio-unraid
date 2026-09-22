from __future__ import annotations

from typing import Any

from ...core.schemas import ComfyImageRef, JobRecord
from ..base import Pipeline
from . import workflow


class MogePlatePipeline(Pipeline):
    id = "moge_plate"
    asset_kind = "scenes"
    display_name = "MoGe from plate"
    description = "Estimate depth and normals from a scene still for Qwen extras."

    @property
    def output_labels(self) -> dict[str, str]:
        return dict(workflow.OUTPUT_LABELS)

    def build_prompt(
        self,
        job: JobRecord,
        *,
        uploaded_images: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        plate = uploaded_images.get("scene") or uploaded_images.get("plate")
        if not plate:
            raise ValueError("scene plate is required for MoGe")
        graph = workflow.build_moge_plate_graph(plate, job_id=job.id)
        seed = int(job.seed or 0)
        return graph, seed

    def map_history_outputs(
        self,
        history: dict[str, Any],
        *,
        job: JobRecord | None = None,
    ) -> dict[str, ComfyImageRef]:
        return workflow.map_history_outputs(history)

    def library_input_keys(self) -> list[str]:
        return ["scene"]
