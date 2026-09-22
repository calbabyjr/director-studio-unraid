from __future__ import annotations

from typing import Any

from ...core.schemas import ComfyImageRef, JobRecord, LibraryAsset
from ..base import Pipeline
from ..prop import workflow as prop_workflow


class CostumePipeline(Pipeline):
    id = "costume"
    asset_kind = "costumes"
    display_name = "Costumes · Wardrobe Sheet"
    description = (
        "Prep one wardrobe photo into a clean multi-view costume sheet the Director "
        "can bind as a Picture on any Shot."
    )

    @property
    def output_labels(self) -> dict[str, str]:
        return dict(prop_workflow.OUTPUT_LABELS)

    def meta_defaults(self) -> dict[str, Any]:
        base = super().meta_defaults()
        base.update(
            {
                "fields": [
                    {
                        "id": "costume_image",
                        "label": "Costume photo",
                        "required": True,
                        "hint": "Front or three-view wardrobe still, ghost mannequin, or garment photo",
                    },
                    {"id": "name", "label": "Name", "required": True},
                    {"id": "notes", "label": "Notes", "required": False},
                ],
            }
        )
        return base

    def build_prompt(
        self,
        job: JobRecord,
        *,
        uploaded_images: dict[str, str],
    ) -> tuple[dict[str, Any], int]:
        image_name = uploaded_images.get("costume") or uploaded_images.get("prop") or ""
        p = job.params or {}
        return prop_workflow.build_prop_prompt(
            image_name=image_name,
            name=job.name or str(p.get("name") or ""),
            notes=job.notes or str(p.get("notes") or "wardrobe / costume reference"),
            seed=job.seed,
            output_prefix=p.get("output_prefix"),
            job_id=job.id,
        )

    def map_history_outputs(
        self,
        history: dict[str, Any],
        *,
        job: JobRecord | None = None,
    ) -> dict[str, ComfyImageRef]:
        return prop_workflow.map_history_outputs(history)

    def library_input_keys(self) -> list[str]:
        return ["costume"]

    def save_to_library(
        self,
        job: JobRecord,
        *,
        name: str | None = None,
        notes: str | None = None,
        project_id: str | None = None,
    ) -> LibraryAsset:
        return super().save_to_library(
            job, name=name, notes=notes, project_id=project_id
        )
