import { useEffect, useMemo, useRef, useState } from "react";
import type { OutputSlot } from "../../shared/api/types";
import { Lightbox } from "../../shared/components/Lightbox";
import { ActorTakesList } from "./ActorTakesList";
import {
  addActorVoiceSample,
  addLibraryAssetFile,
  deleteLibraryAssetFile,
  getActorJob,
  getLibraryAsset,
  updateActorSheet,
  updateLibraryAsset,
  type LibraryAsset,
} from "./api";

const PREVIEW_KEYS = [
  "layout",
  "fullbody_threeview",
  "master",
  "asset_sheet",
  "bust_threeview",
  "wardrobe_ref",
  "image",
  "plate",
  "video",
] as const;

const KEY_LABELS: Record<string, string> = {
  master: "Master",
  fullbody_threeview: "Full-body three-view",
  bust_threeview: "Bust three-view",
  asset_sheet: "Asset sheet",
  wardrobe_ref: "Wardrobe ref",
  face: "Face",
  profile: "Profile",
  back: "Back",
  threeview_extra: "Extra three-view",
  layout: "Layout",
  image: "Image",
  plate: "Plate",
  video: "Video",
  voice: "Voice sample",
  input_actor: "Input · actor",
  input_wardrobe: "Input · wardrobe",
  input_scene: "Input · scene",
};

const IMAGE_FILE_RE = /\.(png|jpe?g|webp|gif)(\?|$)/i;
const AUDIO_FILE_RE = /\.(wav|mp3|m4a|aac|flac|ogg)(\?|$)/i;

const EXTRA_VIEW_KEYS = [
  { value: "face", label: "Face" },
  { value: "profile", label: "Profile" },
  { value: "back", label: "Back" },
  { value: "threeview_extra", label: "Extra three-view" },
  { value: "extra", label: "Extra view" },
] as const;

function labelForKey(key: string): string {
  if (KEY_LABELS[key]) return KEY_LABELS[key];
  if (key.startsWith("voice")) return key === "voice" ? "Voice sample" : `Voice sample ${key.slice(6).replace(/^_/, "")}`;
  if (key.startsWith("input_")) return `Input · ${key.slice(6)}`;
  return key.replace(/_/g, " ");
}

function isAudioSlot(slot: OutputSlot): boolean {
  const haystack = `${slot.filename || ""} ${slot.url || ""} ${slot.key}`;
  return AUDIO_FILE_RE.test(haystack) || slot.key.startsWith("voice");
}

export function assetPreviewUrl(asset: LibraryAsset): string | null {
  if (asset.kind === "voices") return null;
  const urls = asset.urls || {};
  for (const key of PREVIEW_KEYS) {
    if (urls[key] && IMAGE_FILE_RE.test(urls[key])) return urls[key];
  }
  return Object.values(urls).find((url) => url && IMAGE_FILE_RE.test(url)) || null;
}

export function assetSlots(asset: LibraryAsset): OutputSlot[] {
  const urls = asset.urls || {};
  const files = asset.files || {};
  const keys = new Set([...Object.keys(urls), ...Object.keys(files)]);
  const ordered = [
    ...PREVIEW_KEYS.filter((key) => keys.has(key)),
    ...[...keys]
      .filter((key) => !(PREVIEW_KEYS as readonly string[]).includes(key))
      .sort(),
  ];
  return ordered
    .filter((key) => urls[key])
    .map((key) => ({
      key,
      label: labelForKey(key),
      filename: files[key] || null,
      url: urls[key],
    }));
}

function dressFromMeta(meta: LibraryAsset["meta"] | undefined): "unclothed" | "clothed" {
  return meta?.dress_state === "clothed" ? "clothed" : "unclothed";
}

const SHEET_TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export function AssetDetailDialog({
  asset,
  busy = false,
  onClose,
  onDelete,
  onEdit,
  onMoveToCostumes,
  onUpdated,
}: {
  asset: LibraryAsset;
  busy?: boolean;
  onClose: () => void;
  onDelete?: () => void;
  onEdit?: () => void;
  onMoveToCostumes?: () => void;
  onUpdated?: (asset: LibraryAsset) => void;
}) {
  const [current, setCurrent] = useState(asset);
  const slots = useMemo(() => assetSlots(current), [current]);
  const imageSlots = useMemo(() => slots.filter((slot) => !isAudioSlot(slot)), [slots]);
  const audioSlots = useMemo(() => slots.filter(isAudioSlot), [slots]);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [viewKey, setViewKey] = useState("face");
  const [adding, setAdding] = useState<"image" | "voice" | "sheet" | "delete" | null>(null);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [sheetJobId, setSheetJobId] = useState<string | null>(
    typeof current.meta?.sheet_update_job_id === "string" ? current.meta.sheet_update_job_id : null,
  );
  const [sheetStatus, setSheetStatus] = useState<string | null>(null);
  const [dressState, setDressState] = useState<"unclothed" | "clothed">(dressFromMeta(current.meta));
  const fileRef = useRef<HTMLInputElement>(null);
  const voiceRef = useRef<HTMLInputElement>(null);
  const onUpdatedRef = useRef(onUpdated);
  onUpdatedRef.current = onUpdated;
  const canAddImages = current.kind !== "voices";
  const canAddVoice = current.kind === "actors";
  const busyAdd = busy || adding != null;
  const sheetActive = sheetStatus === "queued" || sheetStatus === "uploading" || sheetStatus === "running";
  const lockClose = busyAdd || sheetActive;

  useEffect(() => {
    setCurrent(asset);
  }, [asset]);

  useEffect(() => {
    setDressState(dressFromMeta(current.meta));
  }, [current.id, current.meta?.dress_state]);

  const commit = (updated: LibraryAsset) => {
    setCurrent(updated);
    onUpdatedRef.current?.(updated);
  };

  const onAddImage = async (file: File) => {
    setAdding("image");
    setAddError(null);
    try {
      commit(await addLibraryAssetFile(current.kind, current.id, file, viewKey));
    } catch (cause) {
      setAddError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setAdding(null);
    }
  };

  const onUpdateSheet = async () => {
    setAdding("sheet");
    setAddError(null);
    try {
      const job = await updateActorSheet(current.id, { dress_state: dressState });
      setSheetJobId(job.id);
      setSheetStatus(job.status);
    } catch (cause) {
      setAddError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setAdding(null);
    }
  };

  useEffect(() => {
    if (!sheetJobId || !canAddVoice) return;
    if (sheetStatus && SHEET_TERMINAL.has(sheetStatus)) return;
    let cancelled = false;
    const tick = () => {
      getActorJob(sheetJobId)
        .then(async (job) => {
          if (cancelled) return;
          setSheetStatus(job.status);
          if (job.status === "succeeded") {
            const updated = await getLibraryAsset(current.kind, current.id);
            if (!cancelled) commit(updated);
          }
          if (job.status === "failed" || job.status === "cancelled") {
            setAddError(job.error || `Asset sheet ${job.status}`);
          }
        })
        .catch(() => undefined);
    };
    tick();
    const timer = window.setInterval(tick, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [canAddVoice, current.id, current.kind, sheetJobId, sheetStatus]);

  const onDeleteFile = async (key: string, label: string, filename: string | null) => {
    const detail = filename ? `${label} (${filename})` : label;
    if (!window.confirm(`Remove ${detail} from ${current.name}? Update asset sheet will stop using this still.`)) {
      return;
    }
    setAdding("delete");
    setDeletingKey(key);
    setAddError(null);
    try {
      const updated = await deleteLibraryAssetFile(current.kind, current.id, key);
      commit(updated);
      setLightboxIndex(null);
    } catch (cause) {
      setAddError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setAdding(null);
      setDeletingKey(null);
    }
  };

  const onAddVoice = async (file: File) => {
    setAdding("voice");
    setAddError(null);
    try {
      commit(await addActorVoiceSample(current.id, file));
    } catch (cause) {
      setAddError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setAdding(null);
    }
  };

  const onDressChange = (next: "unclothed" | "clothed") => {
    const previous = dressState;
    setDressState(next);
    void updateLibraryAsset(current.kind, current.id, { dress_state: next })
      .then(commit)
      .catch((cause) => {
        setDressState(previous);
        setAddError(cause instanceof Error ? cause.message : String(cause));
      });
  };

  const filesBlock = slots.length === 0 ? (
    <p className="empty-copy">No files in this asset.</p>
  ) : (
    <>
      {audioSlots.length ? (
        <div className="folder-file-grid">
          {audioSlots.map((slot) => (
            <div key={slot.key} className="folder-file-card voice-file-card">
              <div className="folder-file-label">{slot.label}</div>
              <audio controls preload="metadata" src={slot.url || undefined} />
              {slot.filename ? <div className="muted tiny ellipsis">{slot.filename}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
      {imageSlots.length ? (
        <div className="folder-file-grid">
          {imageSlots.map((slot, index) => (
            <div key={slot.key} className="folder-file-card">
              <button
                type="button"
                className="folder-file-thumb-btn"
                onClick={() => setLightboxIndex(index)}
              >
                <div className="folder-file-thumb">
                  {slot.url ? <img src={slot.url} alt={slot.label} /> : <div className="output-empty">—</div>}
                </div>
              </button>
              <div className="folder-file-label">{slot.label}</div>
              {slot.filename ? <div className="muted tiny ellipsis">{slot.filename}</div> : null}
              <button
                type="button"
                className="btn danger sm"
                disabled={busyAdd || sheetActive}
                aria-label={`Delete ${slot.label}`}
                onClick={() => void onDeleteFile(slot.key, slot.label, slot.filename ?? null)}
              >
                {deletingKey === slot.key ? "Deleting…" : "Delete"}
              </button>
            </div>
          ))}
        </div>
      ) : null}
    </>
  );

  return (
    <>
      <div
        className="folder-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${current.name} assets`}
        onClick={() => { if (!lockClose) onClose(); }}
      >
        <div className="folder-modal-panel folder-modal-asset" onClick={(event) => event.stopPropagation()}>
          <div className="folder-modal-head">
            <div>
              <h2 className="folder-modal-title">{current.name}</h2>
              <p className="muted tiny">
                {current.kind} · {current.pipeline_id || "asset"}
                {current.job_id ? ` · ${current.job_id}` : ""}
                {current.seed != null ? ` · seed ${current.seed}` : ""}
              </p>
              {current.notes ? <p className="folder-modal-notes">{current.notes}</p> : null}
            </div>
            <div className="folder-modal-actions">
              {onEdit ? (
                <button type="button" className="btn secondary sm" disabled={busy} onClick={onEdit}>
                  Edit
                </button>
              ) : null}
              {onMoveToCostumes ? (
                <button
                  type="button"
                  className="btn secondary sm"
                  disabled={busy}
                  onClick={onMoveToCostumes}
                >
                  Move to Costumes
                </button>
              ) : null}
              {onDelete ? (
                <button type="button" className="btn danger sm" disabled={busy} onClick={onDelete}>
                  Delete
                </button>
              ) : null}
              <button type="button" className="btn secondary sm" disabled={lockClose} onClick={onClose}>
                Close
              </button>
            </div>
          </div>

          {canAddImages || canAddVoice || addError ? (
          <div className="folder-modal-toolbar">
            {canAddImages ? (
              <div className="folder-add-image">
                <label>
                  <span className="muted tiny">View</span>
                  <select
                    value={viewKey}
                    disabled={busyAdd}
                    onChange={(event) => setViewKey(event.target.value)}
                    aria-label="New actor view"
                  >
                    {EXTRA_VIEW_KEYS.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="btn secondary sm"
                  disabled={busyAdd}
                  onClick={() => fileRef.current?.click()}
                >
                  {adding === "image" ? "Adding…" : "Add image"}
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  hidden
                  aria-label="Actor view file"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) void onAddImage(file);
                  }}
                />
              </div>
            ) : null}
            {canAddVoice ? (
              <div className="folder-add-image folder-actor-sheet-actions">
                <label>
                  <span className="muted tiny">Body</span>
                  <select
                    value={dressState}
                    disabled={busyAdd || sheetActive}
                    aria-label="Body"
                    onChange={(event) => onDressChange(event.target.value as "unclothed" | "clothed")}
                  >
                    <option value="unclothed">Unclothed / nude</option>
                    <option value="clothed">Clothed</option>
                  </select>
                </label>
                <button
                  type="button"
                  className="btn primary sm"
                  disabled={busyAdd || sheetActive || imageSlots.length === 0}
                  onClick={() => void onUpdateSheet()}
                >
                  {sheetActive || adding === "sheet" ? "Updating sheet…" : "Update asset sheet"}
                </button>
                <button
                  type="button"
                  className="btn secondary sm"
                  disabled={busyAdd || sheetActive}
                  onClick={() => voiceRef.current?.click()}
                >
                  {adding === "voice" ? "Adding…" : "Add voice sample"}
                </button>
                <input
                  ref={voiceRef}
                  type="file"
                  accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg"
                  hidden
                  aria-label="Voice sample file"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) void onAddVoice(file);
                  }}
                />
              </div>
            ) : null}
            {addError ? <p className="field-error">{addError}</p> : null}
            {canAddVoice ? (
              <p className="muted tiny folder-voice-hint">
                Extra stills stay on this actor and feed Update asset sheet, including clothed JPEGs. Delete any still you do not want copied, then Update. Voice samples also become H3-ready Voice library assets (2–15 seconds).
              </p>
            ) : null}
            {sheetStatus && canAddVoice ? (
              <p className="muted tiny" role="status">
                Sheet job {sheetStatus}{sheetJobId ? ` · ${sheetJobId}` : ""}
              </p>
            ) : null}
          </div>
          ) : null}

          <div className="folder-modal-body">
            {filesBlock}
            {current.kind === "actors" ? (
              <ActorTakesList
                actorId={current.id}
                busy={busyAdd}
                onPinned={commit}
              />
            ) : null}
          </div>
        </div>
      </div>

      {lightboxIndex != null ? (
        <div className="folder-modal-lightbox">
          <Lightbox
            slots={imageSlots}
            index={lightboxIndex}
            onClose={() => setLightboxIndex(null)}
            onIndex={setLightboxIndex}
          />
        </div>
      ) : null}
    </>
  );
}
