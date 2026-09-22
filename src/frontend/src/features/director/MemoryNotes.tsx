import { useEffect, useState } from "react";
import {
  addDirectorMemoryNote,
  deleteDirectorMemoryNote,
  getDirectorMemory,
  type DirectorMemoryNote,
} from "./api";

export function MemoryNotes({ projectId, disabled = false }: {
  projectId: string;
  disabled?: boolean;
}) {
  const [notes, setNotes] = useState<DirectorMemoryNote[]>([]);
  const [draft, setDraft] = useState("");
  const [scope, setScope] = useState<"project" | "global">("project");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    const next = await getDirectorMemory(projectId);
    setNotes(next);
  };

  useEffect(() => {
    let active = true;
    setError(null);
    getDirectorMemory(projectId)
      .then((next) => { if (active) setNotes(next); })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => { active = false; };
  }, [projectId]);

  const onAdd = async () => {
    const text = draft.trim();
    if (!text || busy || disabled) return;
    setBusy(true);
    setError(null);
    try {
      await addDirectorMemoryNote(projectId, text, scope);
      setDraft("");
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (note: DirectorMemoryNote) => {
    if (busy || disabled) return;
    setBusy(true);
    setError(null);
    try {
      await deleteDirectorMemoryNote(projectId, note.id);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="director-memory">
      <summary>
        Permanent memory
        <span>{notes.length}</span>
      </summary>
      <p className="director-memory-hint">
        These survive new sessions and are compiled into Director MEMORY.md after every turn. Correct the Director once; it should not repeat the same mistake.
      </p>
      {error ? <div className="banner error">{error}</div> : null}
      {notes.length ? (
        <ul className="director-memory-list">
          {notes.map((note) => (
            <li key={note.id}>
              <div>
                <strong>{note.scope === "global" ? "This director" : "This project"}</strong>
                <span>{note.text}</span>
              </div>
              <button
                type="button"
                className="btn secondary sm"
                disabled={busy || disabled}
                onClick={() => void onDelete(note)}
              >
                Forget
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-copy">No standing notes yet.</p>
      )}
      <form
        className="director-memory-form"
        onSubmit={(event) => {
          event.preventDefault();
          void onAdd();
        }}
      >
        <label>
          <span className="mobile-eyebrow">Standing note</span>
          <input
            aria-label="Standing note"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Remember: never create actors unless asked"
            disabled={busy || disabled}
            maxLength={240}
          />
        </label>
        <select
          aria-label="Note scope"
          value={scope}
          disabled={busy || disabled}
          onChange={(event) => setScope(event.target.value as "project" | "global")}
        >
          <option value="project">This project</option>
          <option value="global">This director</option>
        </select>
        <button type="submit" className="btn primary sm" disabled={busy || disabled || !draft.trim()}>
          Remember
        </button>
      </form>
    </details>
  );
}
