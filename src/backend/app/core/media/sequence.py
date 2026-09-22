"""Storyboard sequence rundown, continuity checks, and rough-cut assembly."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..h3.frames import FPS
from ..jobs.store import load_job
from ..projects.layouts import RefRole
from ..projects.models import PromptSections, Shot, ShotStatus
from ..projects.store import list_shots, load_project, project_dir
from ..schemas import JobRecord, JobStatus
from .clip_generations import (
    ClipGenerationAmbiguous,
    ClipGenerationError,
    ResolvedClip,
    list_project_h3_jobs,
    list_shot_h3_generations,
    resolve_canonical_clip,
    resolve_source_clip,
)

SEQUENCE_DIRNAME = "sequence"
ROUGH_CUT_FILENAME = "rough_cut.mp4"
ASSEMBLY_META_FILENAME = "rough_cut.json"
CONCAT_LIST_FILENAME = "concat.txt"

_PROMPT_FIELDS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)
_ACTIVE_JOB = frozenset(
    {JobStatus.queued, JobStatus.uploading, JobStatus.running}
)
_ACTIVE_SHOT = frozenset({ShotStatus.queued, ShotStatus.running})
_LEFT_RE = re.compile(r"\bleft\b", re.I)
_RIGHT_RE = re.compile(r"\bright\b", re.I)
_SECONDS_PER_DIALOGUE_LINE = 2.2


class SequenceClipStatus(str, Enum):
    missing = "missing"
    ready = "ready"
    failed = "failed"
    running = "running"


class ContinuityIssue(BaseModel):
    severity: Literal["warning", "error"]
    code: str
    shot_id: str
    related_shot_id: str | None = None
    message: str


class SequenceAssembly(BaseModel):
    filename: str
    url: str
    duration_s: float | None = None
    shot_ids: list[str] = Field(default_factory=list)
    missing_shot_ids: list[str] = Field(default_factory=list)
    clip_job_ids: list[str] = Field(default_factory=list)
    created_at: str


class SequenceShotEntry(BaseModel):
    shot_id: str
    index: int
    scene_id: str
    title: str
    script_beat: str
    shot_type: str = ""
    camera_angle: str = ""
    camera_motion: str = ""
    composition: str = ""
    duration_s: float
    status: ShotStatus
    dialogue: list[str] = Field(default_factory=list)
    actor_ids: list[str] = Field(default_factory=list)
    scene_asset_ids: list[str] = Field(default_factory=list)
    costume_ids: list[str] = Field(default_factory=list)
    prop_ids: list[str] = Field(default_factory=list)
    voice_speakers: list[str] = Field(default_factory=list)
    has_layout: bool = False
    has_tail_from_previous: bool = False
    clip_status: SequenceClipStatus = SequenceClipStatus.missing
    clip_job_id: str | None = None
    clip_url: str | None = None
    clip_filename: str | None = None


class SequenceReport(BaseModel):
    project_id: str
    project_name: str
    shot_count: int
    scene_count: int
    planned_duration_s: float
    assembled_duration_s: float
    clips_ready: int
    clips_missing: int
    runtime: str
    shots: list[SequenceShotEntry] = Field(default_factory=list)
    issues: list[ContinuityIssue] = Field(default_factory=list)
    last_assembly: SequenceAssembly | None = None


class SequenceError(ValueError):
    """Sequence report or assembly cannot proceed."""


def sequence_dir(project_id: str) -> Path:
    path = project_dir(project_id) / SEQUENCE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def assembly_url(project_id: str, filename: str = ROUGH_CUT_FILENAME) -> str:
    return f"/api/files/projects/{project_id}/{SEQUENCE_DIRNAME}/{filename}"


def format_runtime(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def seconds_to_timecode(seconds: float, fps: int = FPS) -> str:
    total_frames = max(0, int(round(max(0.0, seconds) * fps)))
    frames = total_frames % fps
    total_seconds = total_frames // fps
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def seconds_to_srt_timestamp(seconds: float) -> str:
    millis = max(0, int(round(max(0.0, seconds) * 1000)))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_sequence_report(project_id: str) -> SequenceReport:
    project = load_project(project_id)
    if project is None:
        raise SequenceError(f"project not found: {project_id}")
    shots = list_shots(project_id)
    h3_jobs = list_project_h3_jobs(project_id)
    entries: list[SequenceShotEntry] = []
    ready_duration = 0.0
    previous: SequenceShotEntry | None = None

    for index, shot in enumerate(shots, start=1):
        generations = list_shot_h3_generations(project_id, shot.id, jobs=h3_jobs)
        clip, clip_status = resolve_shot_clip(
            project_id, shot, generations=generations
        )
        entry = _shot_entry(shot, index=index, clip=clip, clip_status=clip_status)
        if previous is not None:
            entry.has_tail_from_previous = _has_tail_from(shot, previous.shot_id)
        entries.append(entry)
        if clip_status == SequenceClipStatus.ready:
            ready_duration += shot.duration_s
        previous = entry

    issues = _continuity_issues(shots, entries)
    planned = sum(shot.duration_s for shot in shots)
    clips_ready = sum(
        1 for entry in entries if entry.clip_status == SequenceClipStatus.ready
    )
    return SequenceReport(
        project_id=project.id,
        project_name=project.name,
        shot_count=len(entries),
        scene_count=len({entry.scene_id for entry in entries if entry.scene_id}),
        planned_duration_s=round(planned, 3),
        assembled_duration_s=round(ready_duration, 3),
        clips_ready=clips_ready,
        clips_missing=len(entries) - clips_ready,
        runtime=format_runtime(planned),
        shots=entries,
        issues=issues,
        last_assembly=_load_assembly_meta(project_id),
    )


def resolve_shot_clip(
    project_id: str,
    shot: Shot,
    *,
    generations: list[JobRecord] | None = None,
) -> tuple[ResolvedClip | None, SequenceClipStatus]:
    if generations is None:
        generations = list_shot_h3_generations(project_id, shot.id)
    pinned = (shot.h3_job_id or "").strip() or None
    running = shot.status in _ACTIVE_SHOT or any(
        job.status in _ACTIVE_JOB for job in generations
    )
    clip: ResolvedClip | None = None
    try:
        clip = resolve_canonical_clip(
            project_id=project_id,
            source_shot_id=shot.id,
            pinned_job_id=pinned,
            output_kind=None,
            generations=generations,
        )
    except ClipGenerationAmbiguous as exc:
        try:
            clip = resolve_source_clip(
                project_id=project_id,
                source_shot_id=shot.id,
                source_version=None,
                source_job_id=exc.latest_succeeded_job_id,
                output_kind=None,
                generations=generations,
            )
        except ClipGenerationError:
            clip = None
        running = True
    except ClipGenerationError:
        clip = None

    if clip is not None:
        if pinned and clip.source_job_id == pinned:
            return clip, SequenceClipStatus.ready
        return clip, (
            SequenceClipStatus.running if running else SequenceClipStatus.ready
        )
    if running:
        return None, SequenceClipStatus.running
    if generations:
        return None, SequenceClipStatus.failed
    return None, SequenceClipStatus.missing


def render_srt(report: SequenceReport) -> str:
    cues: list[str] = []
    cursor = 0.0
    index = 1
    for entry in report.shots:
        start = cursor
        end = cursor + max(entry.duration_s, 0.1)
        cursor = end
        lines = [line.strip() for line in entry.dialogue if line.strip()]
        if not lines:
            continue
        cues.append(
            f"{index}\n"
            f"{seconds_to_srt_timestamp(start)} --> {seconds_to_srt_timestamp(end)}\n"
            + "\n".join(lines)
        )
        index += 1
    return ("\n\n".join(cues) + ("\n" if cues else "")).lstrip()


def render_edl(report: SequenceReport, *, fps: int = FPS) -> str:
    lines = [
        f"TITLE: {report.project_name or report.project_id}",
        "FCM: NON-DROP FRAME",
        "",
    ]
    record_in = 0.0
    event = 1
    for entry in report.shots:
        duration = max(entry.duration_s, 0.0)
        source_out = duration
        record_out = record_in + duration
        clip_name = entry.clip_filename or f"{entry.shot_id}.mp4"
        lines.append(
            f"{event:03d}  AX       V     C        "
            f"{seconds_to_timecode(0.0, fps)} {seconds_to_timecode(source_out, fps)} "
            f"{seconds_to_timecode(record_in, fps)} {seconds_to_timecode(record_out, fps)}"
        )
        lines.append(f"* FROM CLIP NAME: {clip_name}")
        if entry.title:
            lines.append(f"* SHOT: {entry.index:02d} {entry.title}")
        lines.append("")
        record_in = record_out
        event += 1
    return "\n".join(lines).rstrip() + "\n"


def render_shot_list_csv(report: SequenceReport) -> str:
    header = (
        "index,shot_id,scene_id,title,duration_s,status,clip_status,"
        "shot_type,camera_angle,camera_motion,actors,dialogue"
    )
    rows = [header]
    for entry in report.shots:
        dialogue = " / ".join(line.replace('"', "'") for line in entry.dialogue)
        rows.append(
            ",".join(
                [
                    str(entry.index),
                    _csv(entry.shot_id),
                    _csv(entry.scene_id),
                    _csv(entry.title),
                    f"{entry.duration_s:g}",
                    entry.status.value,
                    entry.clip_status.value,
                    _csv(entry.shot_type),
                    _csv(entry.camera_angle),
                    _csv(entry.camera_motion),
                    _csv(" ".join(entry.actor_ids)),
                    _csv(dialogue),
                ]
            )
        )
    return "\n".join(rows) + "\n"


def assemble_rough_cut(project_id: str) -> SequenceAssembly:
    report = build_sequence_report(project_id)
    clips: list[tuple[SequenceShotEntry, Path]] = []
    missing: list[str] = []
    h3_jobs = list_project_h3_jobs(project_id)
    for entry, shot in zip(report.shots, list_shots(project_id), strict=True):
        generations = list_shot_h3_generations(project_id, shot.id, jobs=h3_jobs)
        clip, status = resolve_shot_clip(project_id, shot, generations=generations)
        if clip is None or status not in {
            SequenceClipStatus.ready,
            SequenceClipStatus.running,
        }:
            missing.append(entry.shot_id)
            continue
        if not clip.path.is_file():
            missing.append(entry.shot_id)
            continue
        clips.append((entry, clip.path))

    if not clips:
        raise SequenceError("no succeeded clips to assemble")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SequenceError("ffmpeg is required to assemble a rough cut")

    out_dir = sequence_dir(project_id)
    output = out_dir / ROUGH_CUT_FILENAME
    concat_path = out_dir / CONCAT_LIST_FILENAME
    concat_path.write_text(
        "".join(_concat_line(path) for _, path in clips),
        encoding="utf-8",
    )

    with tempfile.TemporaryDirectory(prefix="ds_sequence_") as raw_tmp:
        staged = Path(raw_tmp) / ROUGH_CUT_FILENAME
        concat_input = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
        ]
        attempts = [
            [*concat_input, "-c", "copy", str(staged)],
            [
                *concat_input,
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(staged),
            ],
            [
                *concat_input,
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-an",
                "-movflags",
                "+faststart",
                str(staged),
            ],
        ]
        last_error: SequenceError | None = None
        for command in attempts:
            try:
                _run_ffmpeg(command)
                last_error = None
                break
            except SequenceError as exc:
                last_error = exc
                if staged.is_file():
                    staged.unlink()
        if last_error is not None:
            raise last_error
        shutil.copyfile(staged, output)

    duration = _probe_duration(output)
    assembly = SequenceAssembly(
        filename=ROUGH_CUT_FILENAME,
        url=assembly_url(project_id),
        duration_s=duration,
        shot_ids=[entry.shot_id for entry, _ in clips],
        missing_shot_ids=missing,
        clip_job_ids=[
            job_id
            for job_id in (entry.clip_job_id for entry, _ in clips)
            if job_id
        ],
        created_at=_now(),
    )
    (out_dir / ASSEMBLY_META_FILENAME).write_text(
        assembly.model_dump_json(indent=2),
        encoding="utf-8",
    )
    srt_path = out_dir / "rough_cut.srt"
    srt_path.write_text(render_srt(report), encoding="utf-8")
    return assembly


def _shot_entry(
    shot: Shot,
    *,
    index: int,
    clip: ResolvedClip | None,
    clip_status: SequenceClipStatus,
) -> SequenceShotEntry:
    clip_url = None
    if clip is not None:
        job = load_job(clip.source_job_id)
        slot = (job.outputs or {}).get(clip.output_key) if job else None
        clip_url = (slot.url if slot and slot.url else None) or (
            f"/api/files/jobs/{clip.source_job_id}/outputs/{clip.source_filename}"
        )
    return SequenceShotEntry(
        shot_id=shot.id,
        index=index,
        scene_id=shot.scene_id,
        title=shot.title,
        script_beat=shot.script_beat,
        shot_type=shot.shot_type,
        camera_angle=shot.camera_angle,
        camera_motion=shot.camera_motion,
        composition=shot.composition,
        duration_s=shot.duration_s,
        status=shot.status,
        dialogue=list(shot.dialogue or []),
        actor_ids=_ids_for_role(shot, RefRole.actor),
        scene_asset_ids=_ids_for_role(shot, RefRole.scene),
        costume_ids=_ids_for_role(shot, RefRole.costume),
        prop_ids=_ids_for_role(shot, RefRole.prop),
        voice_speakers=[
            (ref.speaker or ref.asset_id) for ref in (shot.voice_refs or [])
        ],
        has_layout=any(layout.asset_id for layout in shot.layout_refs)
        or bool(shot.layout_asset_id),
        clip_status=clip_status,
        clip_job_id=clip.source_job_id if clip else None,
        clip_url=clip_url,
        clip_filename=clip.source_filename if clip else None,
    )


def _ids_for_role(shot: Shot, role: RefRole) -> list[str]:
    return sorted(
        {
            ref.asset_id
            for ref in (shot.refs or [])
            if ref.role == role and ref.asset_id
        }
    )


def _has_tail_from(shot: Shot, previous_shot_id: str) -> bool:
    for layout in shot.layout_refs or []:
        origin = layout.origin
        if origin is None:
            continue
        if getattr(origin, "source_shot_id", None) == previous_shot_id:
            return True
    return False


def _prompt_incomplete(prompt: PromptSections) -> bool:
    return any(not (getattr(prompt, name) or "").strip() for name in _PROMPT_FIELDS)


def _continuity_issues(
    shots: list[Shot], entries: list[SequenceShotEntry]
) -> list[ContinuityIssue]:
    issues: list[ContinuityIssue] = []
    for index, (shot, entry) in enumerate(zip(shots, entries, strict=True)):
        previous_shot = shots[index - 1] if index else None
        previous_entry = entries[index - 1] if index else None

        if entry.clip_status == SequenceClipStatus.missing:
            issues.append(
                ContinuityIssue(
                    severity="warning",
                    code="missing_clip",
                    shot_id=entry.shot_id,
                    message=f"Shot {entry.index:02d} has no succeeded H3 clip.",
                )
            )
        elif entry.clip_status == SequenceClipStatus.failed:
            issues.append(
                ContinuityIssue(
                    severity="error",
                    code="failed_clip",
                    shot_id=entry.shot_id,
                    message=f"Shot {entry.index:02d} H3 generation failed.",
                )
            )

        if not shot.refs:
            issues.append(
                ContinuityIssue(
                    severity="warning",
                    code="missing_refs",
                    shot_id=entry.shot_id,
                    message=f"Shot {entry.index:02d} has no Picture references.",
                )
            )
        if _prompt_incomplete(shot.prompt_sections):
            issues.append(
                ContinuityIssue(
                    severity="warning",
                    code="incomplete_prompt",
                    shot_id=entry.shot_id,
                    message=f"Shot {entry.index:02d} is missing six-section prompt text.",
                )
            )

        spoken = [line.strip() for line in (shot.dialogue or []) if line.strip()]
        if spoken and not shot.voice_refs and not shot.source_audio_path:
            issues.append(
                ContinuityIssue(
                    severity="error",
                    code="missing_voice",
                    shot_id=entry.shot_id,
                    message=(
                        f"Shot {entry.index:02d} has dialogue but no Voice reference "
                        "or source audio."
                    ),
                )
            )
        if spoken and shot.duration_s < len(spoken) * _SECONDS_PER_DIALOGUE_LINE:
            issues.append(
                ContinuityIssue(
                    severity="error",
                    code="dialogue_overrun",
                    shot_id=entry.shot_id,
                    message=(
                        f"Shot {entry.index:02d} duration {shot.duration_s:g}s is short "
                        f"for {len(spoken)} dialogue line(s)."
                    ),
                )
            )

        if previous_shot is None or previous_entry is None:
            continue
        if previous_entry.scene_id != entry.scene_id:
            continue

        if (
            previous_entry.clip_status == SequenceClipStatus.ready
            and not entry.has_tail_from_previous
        ):
            issues.append(
                ContinuityIssue(
                    severity="warning",
                    code="missing_tail_handoff",
                    shot_id=entry.shot_id,
                    related_shot_id=previous_entry.shot_id,
                    message=(
                        f"Shot {entry.index:02d} stays in {entry.scene_id} after "
                        f"Shot {previous_entry.index:02d} but has no tail-frame Layout "
                        "from the previous clip."
                    ),
                )
            )

        if (
            previous_entry.scene_asset_ids
            and entry.scene_asset_ids
            and previous_entry.scene_asset_ids != entry.scene_asset_ids
        ):
            issues.append(
                ContinuityIssue(
                    severity="warning",
                    code="scene_asset_mismatch",
                    shot_id=entry.shot_id,
                    related_shot_id=previous_entry.shot_id,
                    message=(
                        f"Shot {entry.index:02d} uses a different Scene asset than "
                        f"Shot {previous_entry.index:02d} in the same scene."
                    ),
                )
            )

        if (
            previous_entry.actor_ids
            and entry.actor_ids
            and previous_entry.actor_ids != entry.actor_ids
        ):
            issues.append(
                ContinuityIssue(
                    severity="warning",
                    code="actor_mismatch",
                    shot_id=entry.shot_id,
                    related_shot_id=previous_entry.shot_id,
                    message=(
                        f"Shot {entry.index:02d} changes the on-screen Actor set from "
                        f"Shot {previous_entry.index:02d} inside {entry.scene_id}."
                    ),
                )
            )

        if (
            previous_entry.costume_ids
            and entry.costume_ids
            and previous_entry.costume_ids != entry.costume_ids
            and previous_entry.actor_ids == entry.actor_ids
        ):
            issues.append(
                ContinuityIssue(
                    severity="warning",
                    code="wardrobe_change",
                    shot_id=entry.shot_id,
                    related_shot_id=previous_entry.shot_id,
                    message=(
                        f"Shot {entry.index:02d} changes Costume refs from "
                        f"Shot {previous_entry.index:02d} without a scene change."
                    ),
                )
            )

        if _axis_jump(previous_shot.camera_angle, shot.camera_angle):
            issues.append(
                ContinuityIssue(
                    severity="warning",
                    code="axis_jump",
                    shot_id=entry.shot_id,
                    related_shot_id=previous_entry.shot_id,
                    message=(
                        f"Shot {entry.index:02d} camera angle flips left/right from "
                        f"Shot {previous_entry.index:02d} in the same scene."
                    ),
                )
            )
    return _sort_issues(issues)


_ISSUE_RANK = {
    "failed_clip": 0,
    "missing_voice": 1,
    "dialogue_overrun": 2,
    "axis_jump": 3,
    "missing_tail_handoff": 4,
    "scene_asset_mismatch": 5,
    "actor_mismatch": 6,
    "wardrobe_change": 7,
    "missing_clip": 8,
    "missing_refs": 9,
    "incomplete_prompt": 10,
}


def _sort_issues(issues: list[ContinuityIssue]) -> list[ContinuityIssue]:
    return sorted(
        issues,
        key=lambda issue: (
            0 if issue.severity == "error" else 1,
            _ISSUE_RANK.get(issue.code, 50),
            issue.shot_id,
        ),
    )


def _axis_jump(previous_angle: str, current_angle: str) -> bool:
    prev_left = bool(_LEFT_RE.search(previous_angle or ""))
    prev_right = bool(_RIGHT_RE.search(previous_angle or ""))
    curr_left = bool(_LEFT_RE.search(current_angle or ""))
    curr_right = bool(_RIGHT_RE.search(current_angle or ""))
    if prev_left and prev_right or curr_left and curr_right:
        return False
    return (prev_left and curr_right) or (prev_right and curr_left)


def _load_assembly_meta(project_id: str) -> SequenceAssembly | None:
    path = project_dir(project_id) / SEQUENCE_DIRNAME / ASSEMBLY_META_FILENAME
    video = project_dir(project_id) / SEQUENCE_DIRNAME / ROUGH_CUT_FILENAME
    if not path.is_file() or not video.is_file():
        return None
    try:
        return SequenceAssembly.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None


def _concat_line(path: Path) -> str:
    text = path.resolve().as_posix().replace("'", r"'\''")
    return f"file '{text}'\n"


def _run_ffmpeg(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or "").strip()
        message = "ffmpeg failed to assemble the rough cut"
        if detail:
            message = f"{message}: {detail[:400]}"
        raise SequenceError(message) from exc


def _probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        payload = json.loads(result.stdout)
        duration = float((payload.get("format") or {}).get("duration"))
    except (OSError, subprocess.CalledProcessError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return duration if duration > 0 else None


def _csv(value: str) -> str:
    text = value or ""
    if any(char in text for char in ",\"\n"):
        return '"' + text.replace('"', '""') + '"'
    return text


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
