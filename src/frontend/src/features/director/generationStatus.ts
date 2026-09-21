export type GenerationPhase = "queued" | "uploading" | "generating" | "saving";

export interface GenerationJobStatus {
  job_id: string;
  pipeline_id: string;
  kind: "image" | "video";
  status: "queued" | "uploading" | "running";
  phase: GenerationPhase;
  queued_at: string;
}

export interface OllamaResidentModel {
  name?: string | null;
  size?: number | null;
  size_vram?: number | null;
  context_length?: number | null;
}

export interface DirectorVramStatus {
  provider?: string;
  model?: string;
  llm_runtime?: {
    provider?: string;
    model?: string;
    ready?: boolean;
    uses_local_gpu?: boolean;
    loaded_instances?: unknown[];
    error?: string;
  };
  chat_locked: boolean;
  generation_count: number;
  generation_jobs: GenerationJobStatus[];
  owner?: "llm" | "comfy" | null;
  comfy_pipeline?: string | null;
  llm_ready?: boolean;
  ollama_on_gpu?: boolean;
  ollama_size_vram?: number;
  ollama_ps?: OllamaResidentModel[];
  resident_vram?: number;
}

export function formatGenerationElapsed(queuedAt: string, now: Date): string {
  const queuedMs = Date.parse(queuedAt);
  const elapsedSeconds = Number.isFinite(queuedMs)
    ? Math.max(0, Math.floor((now.getTime() - queuedMs) / 1000))
    : 0;
  const hours = Math.floor(elapsedSeconds / 3600);
  const minutes = Math.floor((elapsedSeconds % 3600) / 60);
  const seconds = elapsedSeconds % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(seconds).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

function phaseLabel(job: GenerationJobStatus): string {
  if (job.phase === "queued") return "Queued";
  if (job.phase === "uploading") return "Uploading assets";
  if (job.phase === "saving") return "Saving result";
  return job.kind === "video" ? "Generating video" : "Generating image";
}

export function jobPipelineLabel(job: GenerationJobStatus): string {
  const names: Record<string, string> = {
    h3_ref2va: "H3 video",
    ref_frame: "Layout",
    first_frame: "Layout",
    actor: "Actor",
    prop: "Prop",
    scene: "Scene",
  };
  return names[job.pipeline_id] || (job.kind === "video" ? "Video" : "Image");
}

export function sortedGenerationJobs(status: DirectorVramStatus): GenerationJobStatus[] {
  return [...(status.generation_jobs || [])].sort(
    (left, right) => Date.parse(left.queued_at) - Date.parse(right.queued_at),
  );
}

export function jobActivityLine(job: GenerationJobStatus, now: Date): string {
  return `${phaseLabel(job)} · ${jobPipelineLabel(job)} · ${formatGenerationElapsed(job.queued_at, now)}`;
}

export function generationStatusText(
  status: DirectorVramStatus,
  now: Date,
): string {
  const jobs = sortedGenerationJobs(status);
  const active = jobs[0];
  if (!active) return "";
  const elapsed = formatGenerationElapsed(active.queued_at, now);
  const waiting = Math.max(0, jobs.length - 1);
  const suffix = waiting > 0 ? ` · ${waiting} ${waiting === 1 ? "job" : "jobs"} waiting` : "";
  return `${phaseLabel(active)} · ${jobPipelineLabel(active)} · ${elapsed}${suffix}`;
}

export type ActivityKind = "idle" | "resident" | "llm" | "comfy";

export interface ActivityMeterState {
  kind: ActivityKind;
  label: string;
  jobs?: string[];
  count?: number;
}

function shortModel(name: string): string {
  const base = (name.split("/").pop() || name).trim();
  return base.length > 48 ? `${base.slice(0, 46)}…` : base;
}

function vramGb(bytes: number): string {
  if (!bytes || bytes < 1) return "0 GB";
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

export function activityMeter(status: DirectorVramStatus | null, now: Date): ActivityMeterState {
  if (!status) {
    return { kind: "idle", label: "Activity · connecting to Director…" };
  }

  const jobs = sortedGenerationJobs(status);
  if (jobs.length) {
    const lines = jobs.map((job) => jobActivityLine(job, now));
    const waiting = Math.max(0, jobs.length - 1);
    const suffix = waiting > 0 ? ` · ${waiting} ${waiting === 1 ? "job" : "jobs"} waiting` : "";
    return {
      kind: "comfy",
      label: `ComfyUI · ${lines[0]}${suffix}`,
      jobs: lines,
      count: jobs.length,
    };
  }

  const residents = (status.ollama_ps || []).filter((item) => Number(item.size_vram || 0) > 0);
  const residentBytes = residents.reduce(
    (sum, item) => sum + Number(item.size_vram || 0),
    Number(status.resident_vram || status.ollama_size_vram || 0),
  );
  const residentName = shortModel(String(residents[0]?.name || status.model || "LLM"));

  if (status.owner === "comfy") {
    const pipeline = status.comfy_pipeline ? ` · ${status.comfy_pipeline}` : "";
    return {
      kind: "comfy",
      label: `ComfyUI working${pipeline} · 3090 · first load can sit at 0% util while weights stream into VRAM`,
    };
  }

  if (status.owner === "llm") {
    const phase = status.llm_ready ? "running" : "loading / encoding pictures";
    return {
      kind: "llm",
      label: `Director ${phase} · ${residentName} · ${vramGb(residentBytes)} VRAM · GPU often 0% during load or vision encode`,
    };
  }

  if (residentBytes > 0 || status.ollama_on_gpu) {
    return {
      kind: "resident",
      label: `Idle keep-alive · ${residentName} holding ${vramGb(residentBytes)} · no compute until the next turn (not crashed)`,
    };
  }

  return { kind: "idle", label: "Idle · no LLM or Comfy job" };
}
