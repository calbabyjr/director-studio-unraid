import { parseError } from "../../shared/api/client";

export type SequenceClipStatus = "missing" | "ready" | "failed" | "running";

export interface ContinuityIssue {
  severity: "warning" | "error";
  code: string;
  shot_id: string;
  related_shot_id: string | null;
  message: string;
}

export interface SequenceAssembly {
  filename: string;
  url: string;
  duration_s: number | null;
  shot_ids: string[];
  missing_shot_ids: string[];
  clip_job_ids: string[];
  created_at: string;
}

export interface SequenceShotEntry {
  shot_id: string;
  index: number;
  scene_id: string;
  title: string;
  script_beat: string;
  shot_type: string;
  camera_angle: string;
  camera_motion: string;
  composition: string;
  duration_s: number;
  status: string;
  dialogue: string[];
  actor_ids: string[];
  scene_asset_ids: string[];
  costume_ids: string[];
  prop_ids: string[];
  voice_speakers: string[];
  has_layout: boolean;
  has_tail_from_previous: boolean;
  clip_status: SequenceClipStatus;
  clip_job_id: string | null;
  clip_url: string | null;
  clip_filename: string | null;
}

export interface SequenceReport {
  project_id: string;
  project_name: string;
  shot_count: number;
  scene_count: number;
  planned_duration_s: number;
  assembled_duration_s: number;
  clips_ready: number;
  clips_missing: number;
  runtime: string;
  shots: SequenceShotEntry[];
  issues: ContinuityIssue[];
  last_assembly: SequenceAssembly | null;
}

export type SequenceExportKind = "srt" | "edl" | "csv";

export function sequenceExportUrl(
  projectId: string,
  kind: SequenceExportKind,
): string {
  return `/api/projects/${projectId}/sequence/export/${kind}`;
}

export async function getSequence(projectId: string): Promise<SequenceReport> {
  const res = await fetch(`/api/projects/${projectId}/sequence`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function assembleSequence(
  projectId: string,
): Promise<SequenceAssembly> {
  const res = await fetch(`/api/projects/${projectId}/sequence/assemble`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}
