import { parseError } from "../../shared/api/client";
import type {
  LayoutReviewStatus,
  LayoutSourceRef,
  Project,
  ProjectDetail,
  ProjectMode,
  Shot,
  ShotRef,
} from "../../shared/api/types";
import type { DirectorVramStatus } from "./generationStatus";

export type { Project, ProjectDetail, Shot };

export class DirectorChatError extends Error {
  readonly code: string;
  readonly generationCount: number;

  constructor(message: string, code: string, generationCount = 0) {
    super(message);
    this.name = "DirectorChatError";
    this.code = code;
    this.generationCount = generationCount;
  }
}

async function directorResponseError(res: Response): Promise<Error> {
  try {
    const data = await res.json();
    const detail = data?.detail;
    if (detail && typeof detail === "object" && detail.code) {
      return new DirectorChatError(
        detail.message || res.statusText || "Director chat unavailable",
        String(detail.code),
        Number(detail.generation_count || 0),
      );
    }
    if (typeof detail === "string") return new Error(detail);
    return new Error(JSON.stringify(data));
  } catch {
    return new Error(res.statusText || `HTTP ${res.status}`);
  }
}

export async function getDirectorVramStatus(): Promise<DirectorVramStatus> {
  const res = await fetch("/api/director/vram");
  if (!res.ok) throw await directorResponseError(res);
  return res.json();
}

export async function cancelDirectorJob(jobId: string): Promise<void> {
  const res = await fetch(`/api/director/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
  if (!res.ok) throw await directorResponseError(res);
}

export interface DirectorPatrolStatus {
  enabled: boolean;
  interval_sec: number;
  last_run_at: string | null;
  next_at: string | null;
  projects: Record<string, { count?: number; posted_at?: string; soul_id?: string }>;
}

export async function getDirectorPatrol(): Promise<DirectorPatrolStatus> {
  const res = await fetch("/api/director/patrol");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export interface LayoutBrief {
  purpose: string;
  state_description: string;
  time_hint: string;
  source_refs: LayoutSourceRef[];
}

export interface LayoutReviewRequest {
  status: LayoutReviewStatus;
  feedback: string;
  human_override?: boolean;
}

export async function listProjects(): Promise<Project[]> {
  const res = await fetch("/api/projects");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function createProject(body: {
  name: string;
  script_text: string;
  mode?: ProjectMode;
}): Promise<Project> {
  const res = await fetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  const res = await fetch(`/api/projects/${projectId}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export type ScreenplayInterviewTurn = {
  role: "user" | "assistant";
  content: string;
  choices?: ChoiceQuestion[];
};

export type ScreenplayInterviewState = {
  premise: string;
  turns: ScreenplayInterviewTurn[];
  ready: boolean;
  brief: string;
  updated_at: string;
  drafted?: boolean;
  script_text?: string;
};

export async function getScreenplayInterview(
  projectId: string,
): Promise<ScreenplayInterviewState> {
  const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/screenplay-interview`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function postScreenplayInterview(
  projectId: string,
  body: { message?: string; generate?: boolean; reset?: boolean },
): Promise<ScreenplayInterviewState> {
  const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/screenplay-interview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function updateProject(
  projectId: string,
  body: {
    name?: string;
    script_text?: string;
    script_locked?: boolean;
    script_draft_pending?: boolean;
    soul_id?: string;
  },
): Promise<Project> {
  const res = await fetch(`/api/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function planProject(projectId: string): Promise<ProjectDetail> {
  const res = await fetch(`/api/projects/${projectId}/plan`, { method: "POST" });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export interface ChatImage {
  url: string;
  caption?: string;
  shot_id?: string | null;
}

export type ChoiceQuestion = {
  prompt: string;
  options: string[];
  allow_multiple?: boolean;
};

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  images?: ChatImage[];
  created_at?: string;
  /** Model chain-of-thought (if any) */
  thinking?: string;
  /** Pipeline steps: GPU queue, tools, etc. */
  steps?: string[];
  choices?: ChoiceQuestion[];
}

export interface DirectorMemoryNote {
  id: string;
  text: string;
  scope: "project" | "global";
  source: "user" | "director" | "auto";
  created_at: string;
  updated_at: string;
}

export interface DirectorSoul {
  id: string;
  name: string;
  description: string;
  builtin: boolean;
  markdown: string;
  lessons: string;
  updated_at: string;
}

export async function listDirectorSouls(): Promise<DirectorSoul[]> {
  const res = await fetch("/api/souls");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function createDirectorSoul(body: {
  name: string;
  description?: string;
  markdown?: string;
}): Promise<DirectorSoul> {
  const res = await fetch("/api/souls", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function saveDirectorSoul(
  soulId: string,
  body: { name?: string; description?: string; markdown?: string; lessons?: string },
): Promise<DirectorSoul> {
  const res = await fetch(`/api/souls/${encodeURIComponent(soulId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function deleteDirectorSoul(soulId: string): Promise<void> {
  const res = await fetch(`/api/souls/${encodeURIComponent(soulId)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await parseError(res));
}

export type WorkspaceScope = "global" | "project";

export interface WorkspaceFile {
  name: string;
  scope: WorkspaceScope;
  markdown: string;
  reserved: boolean;
  placeholder: boolean;
  updated_at: string;
}

function workspaceQuery(
  scope: WorkspaceScope,
  projectId?: string | null,
  soulId?: string | null,
): string {
  const params = new URLSearchParams({ scope });
  if (scope === "project" && projectId) params.set("project_id", projectId);
  if (soulId) params.set("soul_id", soulId);
  return params.toString();
}

export async function listWorkspaceFiles(
  scope: WorkspaceScope = "global",
  projectId?: string | null,
  soulId?: string | null,
): Promise<WorkspaceFile[]> {
  const res = await fetch(`/api/workspace?${workspaceQuery(scope, projectId, soulId)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function createWorkspaceFile(body: {
  name: string;
  markdown?: string;
  scope?: WorkspaceScope;
  projectId?: string | null;
  soulId?: string | null;
}): Promise<WorkspaceFile> {
  const res = await fetch("/api/workspace", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: body.name,
      markdown: body.markdown || "",
      scope: body.scope || "global",
      project_id: body.projectId || undefined,
      soul_id: body.soulId || undefined,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function saveWorkspaceFile(
  name: string,
  markdown: string,
  scope: WorkspaceScope = "global",
  projectId?: string | null,
  soulId?: string | null,
): Promise<WorkspaceFile> {
  const res = await fetch(`/api/workspace/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      markdown,
      scope,
      project_id: projectId || undefined,
      soul_id: soulId || undefined,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function deleteWorkspaceFile(
  name: string,
  scope: WorkspaceScope = "global",
  projectId?: string | null,
  soulId?: string | null,
): Promise<void> {
  const res = await fetch(`/api/workspace/${encodeURIComponent(name)}?${workspaceQuery(scope, projectId, soulId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function getDirectorMemory(projectId: string): Promise<DirectorMemoryNote[]> {
  const res = await fetch(`/api/projects/${projectId}/memory`);
  if (!res.ok) throw new Error(await parseError(res));
  const body = await res.json() as { notes?: DirectorMemoryNote[] };
  return body.notes || [];
}

export async function addDirectorMemoryNote(
  projectId: string,
  text: string,
  scope: "project" | "global" = "project",
): Promise<DirectorMemoryNote> {
  const res = await fetch(`/api/projects/${projectId}/memory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, scope }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function deleteDirectorMemoryNote(
  projectId: string,
  noteId: string,
): Promise<void> {
  const res = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/memory/${encodeURIComponent(noteId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export interface DirectorMemoryDocument {
  scope: WorkspaceScope;
  markdown: string;
  placeholder: boolean;
  soul_id?: string | null;
  updated_at: string | null;
}

export async function getDirectorMemoryDocument(
  scope: WorkspaceScope = "global",
  projectId?: string | null,
  soulId?: string | null,
): Promise<DirectorMemoryDocument> {
  const params = new URLSearchParams({ scope });
  if (scope === "project" && projectId) params.set("project_id", projectId);
  if (soulId) params.set("soul_id", soulId);
  const res = await fetch(`/api/memory/document?${params}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function saveDirectorMemoryDocument(
  markdown: string,
  scope: WorkspaceScope = "global",
  projectId?: string | null,
  soulId?: string | null,
): Promise<DirectorMemoryDocument> {
  const res = await fetch("/api/memory/document", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      markdown,
      scope,
      project_id: projectId || undefined,
      soul_id: soulId || undefined,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getDirectorChatHistory(projectId: string): Promise<ChatMessage[]> {
  const res = await fetch(`/api/projects/${projectId}/chat/history`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export interface DirectorChatSessionStatus {
  active: boolean;
  session_id: string | null;
  started_at: string | null;
}

export async function getDirectorChatSession(
  projectId: string,
): Promise<DirectorChatSessionStatus> {
  const res = await fetch(`/api/projects/${projectId}/chat/session`);
  if (!res.ok) throw await directorResponseError(res);
  return res.json();
}

export async function cancelDirectorChatSession(
  projectId: string,
): Promise<DirectorChatSessionStatus> {
  const res = await fetch(`/api/projects/${projectId}/chat/session/cancel`, {
    method: "POST",
  });
  if (!res.ok) throw await directorResponseError(res);
  return res.json();
}

export interface ChatResponse {
  reply: string;
  actions: string[];
  project: Project;
  shots: Shot[];
  images?: ChatImage[];
  thinking?: string;
  steps?: string[];
  choices?: ChoiceQuestion[];
}

export interface ChatCompactionResult {
  compacted: boolean;
  before_tokens: number;
  after_tokens: number;
  session_id: string;
}

export async function getDirectorRuntime(signal?: AbortSignal): Promise<{ runtime: string }> {
  const res = await fetch("/api/director/runtime", { signal });
  if (!res.ok) throw await directorResponseError(res);
  return res.json();
}

export async function compactDirectorContext(projectId: string, signal?: AbortSignal): Promise<ChatCompactionResult> {
  const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/chat/compact`, { method: "POST", signal });
  if (!res.ok) throw await directorResponseError(res);
  return res.json();
}

export interface ChatStreamHandlers {
  onContextUsage?: (usage: ContextUsage) => void;
  onStatus?: (text: string) => void;
  onRuntime?: (text: string) => void;
  onThink?: (text: string) => void;
  onToken?: (text: string) => void;
  onTool?: (text: string) => void;
}

export interface ContextUsage {
  call_id: string;
  sequence: number;
  purpose: "turn" | "compaction";
  provider: string;
  model: string;
  status: "running" | "completed" | "output_truncated" | "context_overflow" | "failed" | "cancelled";
  context_window: number | null;
  capacity_source?: "provider_reported" | "configured_fallback" | null;
  input_budget: number | null;
  output_limit: number | null;
  estimated_input_tokens: number;
  estimated_parts: { system: number; conversation: number; tools: number; format: number };
  image_count: number;
  input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
  thinking_chars: number | null;
  content_chars: number | null;
  tool_calls: number | null;
  finish_reason: string | null;
  elapsed_ms: number;
}

export async function chatWithDirector(
  projectId: string,
  message: string,
  history: { role: string; content: string }[] = [],
): Promise<ChatResponse> {
  const res = await fetch(`/api/projects/${projectId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      history: history.map((h) => ({ role: h.role, content: h.content })),
    }),
  });
  if (!res.ok) throw await directorResponseError(res);
  return res.json();
}

/** Stream Director chat (SSE). Live status / thinking / tokens; final result on resolve. */
export async function chatWithDirectorStream(
  projectId: string,
  message: string,
  history: { role: string; content: string }[] = [],
  handlers: ChatStreamHandlers = {},
  images: File[] = [],
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const serializedHistory = history.map((h) => ({ role: h.role, content: h.content }));
  let path = `/api/projects/${projectId}/chat/stream`;
  let body: BodyInit;
  let headers: HeadersInit;
  if (images.length) {
    path += "/images";
    const form = new FormData();
    form.append("message", message);
    form.append("history", JSON.stringify(serializedHistory));
    images.forEach((image) => form.append("images", image, image.name));
    body = form;
    headers = { Accept: "text/event-stream" };
  } else {
    body = JSON.stringify({ message, history: serializedHistory });
    headers = { "Content-Type": "application/json", Accept: "text/event-stream" };
  }
  const res = await fetch(path, { method: "POST", headers, body, signal });
  if (!res.ok) throw await directorResponseError(res);
  if (!res.body) throw new Error("No stream body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: ChatResponse | null = null;
  let streamError: Error | null = null;

  const handleEvent = (payload: string) => {
    const line = payload.trim();
    if (!line || !line.startsWith("data:")) return;
    const raw = line.slice(5).trim();
    if (!raw) return;
    let ev: {
      type?: string;
      text?: string;
      message?: string;
      code?: string;
      generation_count?: number;
      data?: ChatResponse | ContextUsage;
    };
    try {
      ev = JSON.parse(raw);
    } catch {
      return;
    }
    const t = ev.type || "";
    if (t === "status" && ev.text) handlers.onStatus?.(ev.text);
    else if (t === "runtime" && ev.text) handlers.onRuntime?.(ev.text);
    else if (t === "think" && ev.text) handlers.onThink?.(ev.text);
    else if (t === "token" && ev.text) handlers.onToken?.(ev.text);
    else if (t === "tool" && ev.text) handlers.onTool?.(ev.text);
    else if (t === "context_usage" && ev.data) handlers.onContextUsage?.(ev.data as ContextUsage);
    else if (t === "result" && ev.data) finalResult = ev.data as ChatResponse;
    else if (t === "error") {
      streamError = ev.code
        ? new DirectorChatError(
            ev.message || "stream error",
            ev.code,
            Number(ev.generation_count || 0),
          )
        : new Error(ev.message || "stream error");
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE events separated by blank line
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      for (const line of part.split("\n")) {
        if (line.startsWith("data:")) handleEvent(line);
      }
    }
  }
  if (buffer.trim()) {
    for (const line of buffer.split("\n")) {
      if (line.startsWith("data:")) handleEvent(line);
    }
  }

  if (streamError) throw streamError;
  if (!finalResult) {
    throw new Error("Director chat stream ended without a result");
  }
  return finalResult;
}

export async function queueRefFrame(shotId: string): Promise<Shot[]> {
  const res = await fetch(`/api/shots/${shotId}/ref-frame`, { method: "POST" });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function queueLayout(shotId: string, brief: LayoutBrief): Promise<Shot> {
  const res = await fetch(`/api/shots/${shotId}/layouts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(brief),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function reviewLayout(
  shotId: string,
  layoutRefId: string,
  review: LayoutReviewRequest,
): Promise<Shot> {
  const res = await fetch(`/api/shots/${shotId}/layouts/${layoutRefId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(review),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function selectLayout(
  shotId: string,
  layoutRefId: string,
  selectedForH3: boolean,
): Promise<Shot> {
  const res = await fetch(`/api/shots/${shotId}/layouts/${layoutRefId}/selection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ selected_for_h3: selectedForH3 }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function approveLayout(
  shotId: string,
  opts?: { rewrite_prompt?: boolean; layout_asset_id?: string },
): Promise<Shot> {
  const qs =
    opts?.rewrite_prompt === true ? "?rewrite_prompt=true" : "";
  const res = await fetch(`/api/shots/${shotId}/ref-frame/approve${qs}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      rewrite_prompt: opts?.rewrite_prompt ?? false,
      layout_asset_id: opts?.layout_asset_id,
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function rejectLayout(shotId: string, feedback: string): Promise<Shot> {
  const res = await fetch(`/api/shots/${shotId}/ref-frame/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

// Runs the Picture review + prompt decision now instead of waiting for the idle
// worker. Slow (~3 minutes); 409 while Director chat is running for the project.
export async function refreshShotPrompt(shotId: string): Promise<Shot> {
  const res = await fetch(`/api/shots/${shotId}/refresh-prompt`, { method: "POST" });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getShot(shotId: string): Promise<Shot> {
  const res = await fetch(`/api/shots/${shotId}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export type ShotMaterialSelection = Pick<ShotRef, "role" | "asset_id" | "file_key">;

export async function castActorOnShot(shotId: string, actorId: string): Promise<Shot> {
  const res = await fetch(`/api/shots/${encodeURIComponent(shotId)}/cast-actor`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_id: actorId }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function replaceShotMaterials(
  shotId: string,
  materials: ShotMaterialSelection[],
  opts?: { rewritePrompt?: boolean },
): Promise<Shot> {
  const query = opts?.rewritePrompt ? "?rewrite_prompt=true" : "";
  const res = await fetch(`/api/shots/${shotId}/materials${query}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ materials }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export interface DirectorModelStatus {
  model: string;
  override?: string | null;
  persisted?: string | null;
  env_default?: string;
  source?: string;
  provider?: string;
  reachable?: boolean;
  available?: string[];
}

export async function getDirectorModel(): Promise<DirectorModelStatus> {
  const res = await fetch("/api/director/model");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function setDirectorModel(
  model: string,
  persist = true,
): Promise<DirectorModelStatus> {
  const res = await fetch("/api/director/model", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, persist }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}
