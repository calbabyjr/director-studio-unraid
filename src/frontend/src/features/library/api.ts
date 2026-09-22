import { parseError } from "../../shared/api/client";

export type LibraryKind =
  | "actors"
  | "costumes"
  | "scenes"
  | "props"
  | "layouts"
  | "voices";

export interface LibraryAsset {
  id: string;
  kind: string;
  name: string;
  notes: string;
  pipeline_id: string;
  job_id: string;
  seed: number | null;
  created_at: string;
  files: Record<string, string | null>;
  meta: Record<string, unknown>;
  urls: Record<string, string>;
  project_id: string | null;
}

export async function listLibraryAssets(
  kind: LibraryKind,
  projectId: string | null,
  includeUnassigned = false,
): Promise<LibraryAsset[]> {
  if (!projectId) return [];
  const qs = new URLSearchParams({
    kind,
    project_id: projectId,
    include_unassigned: includeUnassigned ? "true" : "false",
  });
  const res = await fetch(`/api/library?${qs}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function importExternalAsset(opts: {
  file: File;
  kind: LibraryKind;
  name?: string;
  notes?: string;
  projectId: string;
}): Promise<LibraryAsset> {
  const fd = new FormData();
  fd.append("file", opts.file);
  fd.append("kind", opts.kind);
  fd.append("name", opts.name || opts.file.name.replace(/\.[^.]+$/, ""));
  fd.append("notes", opts.notes || "");
  fd.append("project_id", opts.projectId);
  const res = await fetch("/api/library/import", { method: "POST", body: fd });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function deleteLibraryAsset(
  kind: string,
  assetId: string,
): Promise<void> {
  const res = await fetch(
    `/api/library/${encodeURIComponent(kind)}/${encodeURIComponent(assetId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function recastLibraryAsset(
  kind: string,
  assetId: string,
  targetKind: LibraryKind,
): Promise<LibraryAsset> {
  const res = await fetch(
    `/api/library/${encodeURIComponent(kind)}/${encodeURIComponent(assetId)}/kind`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: targetKind }),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function addLibraryAssetFile(
  kind: string,
  assetId: string,
  file: File,
  key?: string,
): Promise<LibraryAsset> {
  const body = new FormData();
  body.set("file", file, file.name);
  if (key?.trim()) body.set("key", key.trim());
  const res = await fetch(
    `/api/library/${encodeURIComponent(kind)}/${encodeURIComponent(assetId)}/files`,
    { method: "POST", body },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function addActorVoiceSample(
  assetId: string,
  file: File,
  opts?: { name?: string; notes?: string },
): Promise<LibraryAsset> {
  const body = new FormData();
  body.set("file", file, file.name);
  if (opts?.name?.trim()) body.set("name", opts.name.trim());
  if (opts?.notes?.trim()) body.set("notes", opts.notes.trim());
  const res = await fetch(
    `/api/library/actors/${encodeURIComponent(assetId)}/voice`,
    { method: "POST", body },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function updateLibraryAsset(
  kind: string,
  assetId: string,
  metadata: { name: string; notes: string },
): Promise<LibraryAsset> {
  const res = await fetch(
    `/api/library/${encodeURIComponent(kind)}/${encodeURIComponent(assetId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(metadata),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export interface ActorTake {
  id: string;
  status: string;
  created_at: string;
  pinned: boolean;
}

export async function listActorTakes(
  assetId: string,
): Promise<{ items: ActorTake[] }> {
  const res = await fetch(
    `/api/library/actors/${encodeURIComponent(assetId)}/takes`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getLibraryAsset(
  kind: string,
  assetId: string,
): Promise<LibraryAsset> {
  const res = await fetch(
    `/api/library/${encodeURIComponent(kind)}/${encodeURIComponent(assetId)}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function updateActorSheet(assetId: string): Promise<{
  id: string;
  status: string;
  error: string | null;
}> {
  const res = await fetch(
    `/api/library/actors/${encodeURIComponent(assetId)}/update-sheet`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getActorJob(jobId: string): Promise<{
  id: string;
  status: string;
  error: string | null;
}> {
  const res = await fetch(`/api/actors/jobs/${encodeURIComponent(jobId)}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function pinActorTake(
  assetId: string,
  jobId: string,
): Promise<LibraryAsset> {
  const res = await fetch(
    `/api/library/actors/${encodeURIComponent(assetId)}/takes/${encodeURIComponent(jobId)}/pin`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}
