"""Prop design generation and acceptance tools."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from ....core.library.images import resolve_asset_image
from ....core.library.store import load_asset
from ....core.schemas import JobStatus
from ..intent import actor_acceptance_intent

_LIBRARY_KINDS = ("scenes", "props", "actors", "costumes", "layouts")
_KIND_ROLE = {
    "scenes": "scene",
    "props": "prop",
    "actors": "actor",
    "costumes": "costume",
    "layouts": "layout_ref_frame",
}


def _load_project_asset(asset_id: str, project_id: str):
    for kind in _LIBRARY_KINDS:
        asset = load_asset(kind, asset_id)
        if asset is None:
            continue
        if asset.project_id and asset.project_id != project_id:
            continue
        return asset
    return None


def _source_image(
    *,
    args: dict[str, Any],
    project_id: str,
    user_uploads: list[dict[str, Any]] | None,
) -> tuple[str, bytes]:
    source_asset_id = str(args.get("source_asset_id") or "").strip()
    file_key = str(args.get("file_key") or "").strip() or None
    image_index = args.get("image_index")

    if source_asset_id:
        asset = _load_project_asset(source_asset_id, project_id)
        if asset is None:
            raise ValueError(
                f"Source asset not found in this project: {source_asset_id}"
            )
        resolved = resolve_asset_image(
            asset,
            role=_KIND_ROLE.get(asset.kind, "other"),
            file_key=file_key,
        )
        if resolved is None:
            raise ValueError(
                f"Source asset {source_asset_id} has no usable image"
                + (f" for file_key {file_key}" if file_key else "")
            )
        filename, data, _used = resolved
        return filename, data

    if image_index is not None:
        try:
            index = int(image_index)
        except (TypeError, ValueError) as exc:
            raise ValueError("image_index must be an integer") from exc
        uploads = user_uploads or []
        if index < 1 or index > len(uploads):
            raise ValueError(
                f"image_index must identify one of the {len(uploads)} current chat uploads"
            )
        upload = uploads[index - 1]
        raw = upload.get("data_b64") or upload.get("bytes") or upload.get("data") or ""
        if isinstance(raw, bytes):
            data = raw
        else:
            try:
                data = base64.b64decode(str(raw), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("chat upload image could not be decoded") from exc
        if not data:
            raise ValueError("chat upload image is empty")
        filename = str(upload.get("filename") or upload.get("name") or f"image_{index}.png")
        return filename, data

    raise ValueError(
        "queue_prop_design requires source_asset_id (library still that contains "
        "the object) or image_index (current chat upload)"
    )


async def handle_prop_tool(
    *,
    name: str,
    args: dict[str, Any],
    project_id: str,
    user_feedback: str,
    runtime: Any,
    actions: list[str],
    notes: list[str],
    result_payloads: list[dict[str, Any]] | None,
    images: list[Any] | None,
    user_uploads: list[dict[str, Any]] | None,
) -> bool:
    if name == "queue_prop_design":
        prop_name = str(args.get("name") or "").strip()
        description = str(args.get("description") or "").strip()
        generation_prompt = str(args.get("generation_prompt") or "").strip()
        if not prop_name or not description or not generation_prompt:
            raise ValueError(
                "queue_prop_design requires name, description, and generation_prompt"
            )
        filename, data = _source_image(
            args=args,
            project_id=project_id,
            user_uploads=user_uploads,
        )
        notes_blob = description
        if generation_prompt and generation_prompt not in description:
            notes_blob = f"{description} Isolate: {generation_prompt}"
        job = runtime.create_job(
            pipeline_id="prop",
            asset_kind="props",
            name=prop_name,
            notes=notes_blob[:2000],
            params={
                "name": prop_name,
                "notes": notes_blob[:2000],
                "generation_prompt": generation_prompt,
                "source_asset_id": str(args.get("source_asset_id") or "").strip(),
                "file_key": str(args.get("file_key") or "").strip(),
            },
            project_id=project_id,
        )
        await runtime.start_pipeline_job(job, images={"prop": (filename, data)})
        terminal = await runtime.await_pipeline_job(job.id)
        if terminal is None:
            raise ValueError(f"Prop design job disappeared: {job.id}")
        if terminal.status != JobStatus.succeeded:
            raise ValueError(
                str(
                    terminal.error
                    or f"Prop design job status is {terminal.status.value}"
                )
            )
        preview = next(
            (
                terminal.outputs[key]
                for key in ("master", "asset_sheet")
                if key in terminal.outputs and terminal.outputs[key].url
            ),
            None,
        )
        if preview is None or not preview.url:
            raise ValueError("Prop design completed without a preview image")
        actions.append(f"prop_design:{terminal.id}")
        if images is not None:
            images.append(
                runtime.chat_image_factory(
                    url=preview.url,
                    caption=f"Prop design · {prop_name} · {terminal.id}",
                )
            )
        if result_payloads is not None:
            result_payloads.append(
                {
                    "ok": True,
                    "job_id": terminal.id,
                    "review_status": "pending_review",
                }
            )
        notes.append(
            f"Prop design job {terminal.id} is ready for review. "
            "Say ‘save this’ to save it to the Prop library."
        )
        return True

    if name == "accept_prop_design":
        if not actor_acceptance_intent(user_feedback):
            raise ValueError(
                "accept_prop_design requires explicit acceptance in the current user turn"
            )
        job_id = str(args.get("job_id") or "").strip()
        job = runtime.load_job(job_id)
        if (
            job is None
            or job.pipeline_id != "prop"
            or job.asset_kind != "props"
            or (job.project_id or None) != project_id
        ):
            raise ValueError(f"Prop design job not found in this project: {job_id}")
        if job.status != JobStatus.succeeded:
            raise ValueError(
                f"Prop design job status is {job.status.value}; it cannot be saved"
            )
        if job.library_asset_id:
            prop_asset = load_asset("props", job.library_asset_id)
            if prop_asset is None:
                raise ValueError(f"Saved Prop asset is missing: {job.library_asset_id}")
        else:
            prop_asset = runtime.get_pipeline(job.pipeline_id).save_to_library(
                job,
                name=str(args.get("name") or "").strip() or None,
                notes=str(args.get("notes") or "").strip() or None,
                project_id=project_id,
            )
        actions.append(f"accept_prop_design:{prop_asset.id}")
        preview_url = next(
            (
                prop_asset.urls.get(key)
                for key in ("master", "asset_sheet")
                if prop_asset.urls.get(key)
            ),
            None,
        )
        if images is not None and preview_url:
            images.append(
                runtime.chat_image_factory(
                    url=preview_url,
                    caption=f"Prop · {prop_asset.name}",
                )
            )
        notes.append(
            f"Saved Prop {prop_asset.id} ({prop_asset.name}) to this project's library."
        )
        return True

    return False
