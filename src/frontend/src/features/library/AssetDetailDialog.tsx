import { useEffect, useMemo, useRef, useState } from "react";
import type { OutputSlot } from "../../shared/api/types";
import { Lightbox } from "../../shared/components/Lightbox";
import { ActorTakesList } from "./ActorTakesList";
import {
  addActorVoiceSample,
  addLibraryAssetFile,
  getActorJob,
  getLibraryAsset,
  updateActorSheet,
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
  const slots = useMemo(() => assetSlots(asset), [asset]);
  const imageSlots = useMemo(() => slots.filter((slot) => !isAudioSlot(slot)), [slots]);
  const audioSlots = useMemo(() => slots.filter(isAudioSlot), [slots]);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [viewKey, setViewKey] = useState("face");
  const [adding, setAdding] = useState<"image" | "voice" | "sheet" | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [sheetJobId, setSheetJobId] = useState<string | null>(
    typeof asset.meta?.sheet_update_job_id === "string" ? asset.meta.sheet_update_job_id : null,
  );
  const [sheetStatus, setSheetStatus] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const voiceRef = useRef<HTMLInputElement>(null);
  const canAddImages = asset.kind !== "voices";
  const canAddVoice = asset.kind === "actors";
  const busyAdd = busy || adding != null;

  const onAddImage = async (file: File) => {
    setAdding("image");
    setAddError(null);
    try {
      const updated = await addLibraryAssetFile(asset.kind, asset.id, file, viewKey);
      onUpdated?.(updated);
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
      const job = await updateActorSheet(asset.id);
      setSheetJobId(job.id);
      setSheetStatus(job.status);
    } catch (cause) {
      setAddError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setAdding(null);
    }
  };

  const sheetActive = sheetStatus === "queued" || sheetStatus === "uploading" || sheetStatus === "running";

  useEffect(() => {
    if (!sheetJobId || !canAddVoice) return;
    let cancelled = false;
    const tick = () => {
      getActorJob(sheetJobId)
        .then(async (job) => {
          if (cancelled) return;
          setSheetStatus(job.status);
          if (job.status === "succeeded") {
            const updated = await getLibraryAsset(asset.kind, asset.id);
            if (!cancelled) onUpdated?.(updated);
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
  }, [asset.id, asset.kind, canAddVoice, onUpdated, sheetJobId]);

  const onAddVoice = async (file: File) => {
    setAdding("voice");
    setAddError(null);
    try {
      const updated = await addActorVoiceSample(asset.id, file);
      onUpdated?.(updated);
    } catch (cause) {
      setAddError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setAdding(null);
    }
  };

  return (
    <>
      <div
        className="folder-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${asset.name} assets`}
        onClick={onClose}
      >
        <div className="folder-modal-panel" onClick={(event) => event.stopPropagation()}>
          <div className="folder-modal-head">
            <div>
              <h2 className="folder-modal-title">{asset.name}</h2>
              <p className="muted tiny">
                {asset.kind} · {asset.pipeline_id || "asset"}
                {asset.job_id ? ` · ${asset.job_id}` : ""}
                {asset.seed != null ? ` · seed ${asset.seed}` : ""}
              </p>
              {asset.notes ? <p className="folder-modal-notes">{asset.notes}</p> : null}
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
              <button type="button" className="btn secondary sm" onClick={onClose}>
                Close
              </button>
            </div>
          </div>

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
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void onAddImage(file);
                }}
              />
              {canAddVoice ? (
                <>
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
                </>
              ) : null}
              {addError ? <p className="field-error">{addError}</p> : null}
            </div>
          ) : null}

          {canAddVoice ? (
            <p className="muted tiny folder-voice-hint">
              Extra stills stay on this actor. Update asset sheet rebuilds the master and three-view from those photos, then keeps the extras. Voice samples also become H3-ready Voice library assets (2–15 seconds).
            </p>
          ) : null}
          {sheetStatus && canAddVoice ? (
            <p className="muted tiny" role="status">
              Sheet job {sheetStatus}{sheetJobId ? ` · ${sheetJobId}` : ""}
            </p>
          ) : null}

          {asset.kind === "actors" ? (
            <ActorTakesList
              actorId={asset.id}
              busy={busyAdd}
              onPinned={onUpdated}
            />
          ) : null}

          {slots.length === 0 ? (
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
                    <button
                      key={slot.key}
                      type="button"
                      className="folder-file-card"
                      onClick={() => setLightboxIndex(index)}
                    >
                      <div className="folder-file-thumb">
                        {slot.url ? <img src={slot.url} alt={slot.label} /> : <div className="output-empty">—</div>}
                      </div>
                      <div className="folder-file-label">{slot.label}</div>
                      {slot.filename ? <div className="muted tiny ellipsis">{slot.filename}</div> : null}
                    </button>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>

      {lightboxIndex != null ? (
        <Lightbox
          slots={imageSlots}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onIndex={setLightboxIndex}
        />
      ) : null}
    </>
  );
}
