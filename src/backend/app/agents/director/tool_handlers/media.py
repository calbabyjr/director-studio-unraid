"""Cross-shot media extraction and project status tools."""

from __future__ import annotations

from typing import Any

from ....core.media.clip_generations import ClipGenerationAmbiguous
from ....core.media import sequence, tail_frame
from ....core.projects.models import Project, Shot
from ....core.projects.store import load_shot
from ..intent import material_review_target_shot_id


async def handle_media_tool(
    *,
    name: str,
    args: dict[str, Any],
    project_id: str,
    project: Project,
    shots: list[Shot],
    runtime: Any,
    actions: list[str],
    notes: list[str],
    touched: set[str],
    result_payloads: list[dict[str, Any]] | None,
    images: list[Any] | None,
    user_feedback: str,
) -> bool:
    if name in {"get_status", "status"}:
        shot_id = args.get("shot_id")
        if shot_id:
            selected = next((shot for shot in shots if shot.id == shot_id), None)
            if result_payloads is not None:
                result_payloads.append(
                    {"ok": True, "shot": selected.model_dump(mode="json")}
                    if selected else {"ok": False, "error": "Shot not found in this project"}
                )
            notes.append(f"Read Shot {shot_id}." if selected else "Shot not found in this project.")
            return True
        actions.append("status")
        notes.append(runtime.status_summary(project, shots))
        return True
    if name == "review_sequence":
        try:
            report = sequence.build_sequence_report(project_id)
        except sequence.SequenceError as exc:
            if result_payloads is not None:
                result_payloads.append({"ok": False, "error": str(exc)})
            notes.append(f"review_sequence failed: {exc}")
            return True
        payload = report.model_dump(mode="json")
        if result_payloads is not None:
            result_payloads.append({"ok": True, "sequence": payload})
        actions.append("review_sequence")
        issue_count = len(report.issues)
        notes.append(
            f"Sequence: {report.shot_count} shot(s), planned {report.runtime}, "
            f"{report.clips_ready} clip(s) ready, {issue_count} continuity issue(s)."
        )
        for issue in report.issues[:12]:
            related = f" (after {issue.related_shot_id})" if issue.related_shot_id else ""
            notes.append(
                f"- [{issue.severity}] {issue.code} on {issue.shot_id}{related}: "
                f"{issue.message}"
            )
        if issue_count > 12:
            notes.append(f"- … {issue_count - 12} more issue(s)")
        return True
    if name == "assemble_sequence":
        try:
            assembly = sequence.assemble_rough_cut(project_id)
        except sequence.SequenceError as exc:
            if result_payloads is not None:
                result_payloads.append({"ok": False, "error": str(exc)})
            notes.append(f"assemble_sequence failed: {exc}")
            return True
        if result_payloads is not None:
            result_payloads.append({"ok": True, "assembly": assembly.model_dump(mode="json")})
        actions.append("assemble_sequence")
        skipped = (
            f" Skipped {len(assembly.missing_shot_ids)} shot(s) without clips."
            if assembly.missing_shot_ids
            else ""
        )
        duration = (
            f" Duration {assembly.duration_s:.1f}s."
            if assembly.duration_s
            else ""
        )
        notes.append(
            f"Assembled a rough cut from {len(assembly.shot_ids)} clip(s) at "
            f"{assembly.url}.{duration}{skipped}"
        )
        return True
    if name != "extract_clip_tail_frame":
        return False

    source_shot_id = str(args.get("source_shot_id") or "").strip()
    target_shot_id = str(args.get("target_shot_id") or "").strip()
    material_review_target = material_review_target_shot_id(user_feedback)
    if material_review_target and target_shot_id != material_review_target:
        raise ValueError(
            "Material review tail-frame extraction is restricted to the changed Shot "
            f"{material_review_target}"
        )
    if not source_shot_id or not target_shot_id:
        notes.append("extract_clip_tail_frame: specify source_shot_id and target_shot_id")
        return True

    def optional_selector(key: str) -> str | None:
        value = args.get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    try:
        extracted = tail_frame.extract_clip_tail_frame(
            project_id=project_id,
            source_shot_id=source_shot_id,
            target_shot_id=target_shot_id,
            source_version=optional_selector("source_version"),
            source_job_id=optional_selector("source_job_id"),
            output_kind=optional_selector("output_kind"),
        )
    except ClipGenerationAmbiguous as exc:
        blocking = (
            exc.blocking_status.value
            if hasattr(exc.blocking_status, "value")
            else str(exc.blocking_status)
        )
        if result_payloads is not None:
            result_payloads.append(
                {
                    "ok": False,
                    "needs_clarification": True,
                    "error": str(exc),
                    "latest_succeeded_job_id": exc.latest_succeeded_job_id,
                    "blocking_job_id": exc.blocking_job_id,
                    "blocking_status": blocking,
                }
            )
        notes.append(
            "extract_clip_tail_frame needs clarification: "
            f"{exc}. Latest completed job is {exc.latest_succeeded_job_id}; "
            f"a newer job {exc.blocking_job_id} is {blocking}. Ask whether to "
            "use the latest completed generation."
        )
        return True

    actions.append(f"extract_clip_tail_frame:{target_shot_id}")
    touched.add(target_shot_id)
    if result_payloads is not None:
        result_payloads.append(extracted)
    source_shot = load_shot(project_id, source_shot_id)
    target_shot = load_shot(project_id, target_shot_id)
    source_title = source_shot.title if source_shot else extracted["source_shot_id"]
    target_title = target_shot.title if target_shot else extracted["target_shot_id"]
    candidate = runtime.extracted_tail_frame_image(
        extracted,
        source_title=source_title,
        target_title=target_title,
    )
    if candidate is not None and images is not None:
        images.append(candidate)
    notes.append(
        f"Extracted the tail frame of **{source_title}** "
        f"(`{extracted['source_shot_id']}`) v{extracted['source_version']} "
        f"(job {extracted['source_job_id']}, {extracted['output_kind']}) "
        f"for **{target_title}** (`{extracted['target_shot_id']}`). "
        f"LayoutReference {extracted['layout_ref_id']} is pending human review "
        "and is not yet in the H3 Picture pack."
    )
    return True
