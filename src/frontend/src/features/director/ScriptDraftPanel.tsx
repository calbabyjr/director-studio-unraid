import { useEffect, useState } from "react";
import { updateProject } from "./api";
import type { Project } from "../../shared/api/types";

export function ScriptDraftPanel({
  project,
  disabled,
  onUpdated,
}: {
  project: Project;
  disabled?: boolean;
  onUpdated?: (project: Project) => void;
}) {
  const [draft, setDraft] = useState(project.script_text || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const locked = Boolean(project.script_locked);
  const pending = Boolean(project.script_draft_pending) && !locked;
  const [expanded, setExpanded] = useState(pending);

  useEffect(() => {
    setDraft(project.script_text || "");
  }, [project.id, project.script_text]);

  useEffect(() => {
    if (pending) setExpanded(true);
  }, [pending]);

  if (!(project.script_text || "").trim() && !pending) return null;

  const save = async (body: {
    script_text?: string;
    script_locked?: boolean;
    script_draft_pending?: boolean;
  }) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await updateProject(project.id, body);
      onUpdated?.(updated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const statusLabel = locked
    ? "Screenplay locked"
    : pending
      ? "Draft pending approval"
      : "Screenplay";
  const title = locked ? "Source of truth" : pending ? "Review the pages" : "Screenplay";

  return (
    <section
      className={`script-draft-panel${expanded ? "" : " is-collapsed"}`}
      aria-label="Screenplay draft"
    >
      <header className="script-draft-head">
        <button
          type="button"
          className="script-draft-toggle"
          aria-expanded={expanded}
          aria-label={expanded ? "Hide screenplay" : "Show screenplay"}
          onClick={() => setExpanded((open) => !open)}
        >
          <span className="muted tiny">{statusLabel}</span>
          <h3>{title}</h3>
        </button>
        <div className="script-draft-actions">
          {locked ? (
            <button
              type="button"
              className="btn ghost sm"
              disabled={disabled || busy}
              onClick={() => void save({ script_locked: false, script_draft_pending: true })}
            >
              Unlock to edit
            </button>
          ) : expanded || pending ? (
            <>
              <button
                type="button"
                className="btn secondary sm"
                disabled={disabled || busy || draft === (project.script_text || "")}
                onClick={() => void save({ script_text: draft })}
              >
                Save draft
              </button>
              <button
                type="button"
                className="btn primary sm"
                disabled={disabled || busy || !draft.trim()}
                onClick={() => void save({ script_text: draft, script_locked: true })}
              >
                Approve and lock
              </button>
            </>
          ) : null}
        </div>
      </header>
      {expanded ? (
        <>
          <textarea
            className="script-draft-editor"
            value={draft}
            readOnly={locked || busy}
            disabled={disabled}
            spellCheck={false}
            aria-label="Screenplay"
            onChange={(event) => setDraft(event.target.value)}
          />
          {!locked ? (
            <p className="muted tiny">
              Shot planning, casting, and H3 stay off until you lock these pages.
            </p>
          ) : null}
        </>
      ) : null}
      {error ? <p className="field-error">{error}</p> : null}
    </section>
  );
}
