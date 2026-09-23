import { useState } from "react";
import { importExternalAsset, type LibraryKind } from "./api";

const KIND_LABELS: Record<LibraryKind, string> = {
  actors: "Actors",
  scenes: "Scenes",
  props: "Props",
  costumes: "Costumes",
  layouts: "Layouts",
  voices: "Voices",
};

const KIND_SINGULAR: Record<LibraryKind, string> = {
  actors: "actor",
  scenes: "scene",
  props: "prop",
  costumes: "costume",
  layouts: "layout",
  voices: "voice",
};

export function libraryKindLabel(kind: LibraryKind): string {
  return KIND_LABELS[kind];
}

export function AssetImportDialog({
  kind,
  projectId,
  onClose,
  onImported,
}: {
  kind: LibraryKind;
  projectId: string;
  onClose: () => void;
  onImported: () => void;
}) {
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isVoice = kind === "voices";
  const label = libraryKindLabel(kind);
  const singular = KIND_SINGULAR[kind];
  const titleId = `asset-import-${kind}-title`;
  const canImport = Boolean(file) && !busy && (!isVoice || Boolean(name.trim()));

  const onImport = async () => {
    if (!file) {
      setError(isVoice ? "Choose an audio file first." : "Choose an image file first.");
      return;
    }
    if (isVoice && !name.trim()) {
      setError("Name is required for Voice assets.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await importExternalAsset({
        file,
        kind,
        name: name.trim() || undefined,
        notes: notes.trim() || undefined,
        projectId,
      });
      onImported();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="folder-modal asset-import-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={() => { if (!busy) onClose(); }}
    >
      <div className="folder-modal-panel asset-import-modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="folder-modal-head">
          <div>
            <span className="mobile-eyebrow">Add to project library</span>
            <h2 className="folder-modal-title" id={titleId}>Import {label}</h2>
          </div>
          <button type="button" className="btn secondary sm" onClick={onClose} disabled={busy}>
            Close import
          </button>
        </div>

        {error ? <div className="banner error">{error}</div> : null}
        <p className="field-hint">
          {isVoice
            ? "Name the speaker, choose a clean 2–15 second sample, then Import."
            : "Choose a clean reference, then Import. A clear name and short notes help the Director assign it."}
        </p>
        <div className="import-form">
          <label className="field">
            <span>Name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={isVoice ? "e.g. Mia" : "Asset name"}
              disabled={busy}
              required={isVoice}
            />
          </label>
          <label className="field field-span-2">
            <span>{isVoice ? "Description" : "Notes"}</span>
            <input
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder={isVoice ? "Warm · intimate calm delivery" : "Continuity or usage notes"}
              disabled={busy}
            />
          </label>
          <label className="field field-span-2">
            <span>{isVoice ? "Audio file" : "Image file"}</span>
            <input
              type="file"
              accept={isVoice
                ? "audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg"
                : "image/png,image/jpeg,image/jpg,image/webp,image/gif,.png,.jpg,.jpeg,.webp,.gif"}
              disabled={busy}
              onChange={(event) => {
                setFile(event.target.files?.[0] || null);
                setError(null);
              }}
            />
            {file ? <span className="asset-import-file-name">{file.name}</span> : null}
          </label>
        </div>
        <footer className="asset-import-actions">
          <button
            type="button"
            className="btn primary"
            disabled={!canImport}
            onClick={() => void onImport()}
          >
            {busy ? "Importing…" : `Import ${singular}`}
          </button>
        </footer>
      </div>
    </div>
  );
}
