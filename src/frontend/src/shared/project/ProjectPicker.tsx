import { useState } from "react";
import { createPortal } from "react-dom";
import type { ProjectMode } from "../api/types";
import { useProject } from "./ProjectContext";

export function ProjectPicker() {
  const {
    projects,
    projectId,
    project,
    loading,
    error,
    setProjectId,
    createAndSelect,
    renameProject,
    refreshProjects,
  } = useProject();
  // Keep the active project first. Changing an <option> label can make the
  // browser fire change with the first option, which swapped projects on rename.
  const orderedProjects = projectId
    ? [
        ...projects.filter((p) => p.id === projectId),
        ...projects.filter((p) => p.id !== projectId),
      ]
    : projects;
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState("");
  const [renameName, setRenameName] = useState("");
  const [newMode, setNewMode] = useState<ProjectMode>("director");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  function closeCreateForm() {
    setCreating(false);
    setNewName("");
    setNewMode("director");
    setLocalError(null);
  }

  function closeRenameForm() {
    setRenaming(false);
    setRenameName("");
    setLocalError(null);
  }

  function openRenameForm() {
    setLocalError(null);
    setRenameName(project?.name || "");
    setRenaming(true);
  }

  async function onCreate() {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    setLocalError(null);
    try {
      await createAndSelect(name, "", newMode);
      closeCreateForm();
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onRename() {
    const name = renameName.trim();
    if (!name || !projectId) return;
    setBusy(true);
    setLocalError(null);
    try {
      await renameProject(name);
      closeRenameForm();
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
    <div className="project-picker">
      <label className="project-picker-label" htmlFor="global-project">
        Project
      </label>
      <select
        id="global-project"
        key={`${projectId || "none"}:${project?.name || ""}`}
        className="project-select"
        disabled={loading || busy}
        value={projectId || ""}
        onChange={(e) => {
          const next = e.target.value || null;
          if (next === projectId) return;
          setProjectId(next);
        }}
        title={project ? `${project.name} (${project.id})` : "Select project"}
      >
        {orderedProjects.length === 0 ? (
          <option value="">No projects</option>
        ) : (
          orderedProjects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))
        )}
      </select>
      <button
        type="button"
        className="btn secondary btn-sm"
        disabled={busy}
        onClick={() => {
          setLocalError(null);
          setCreating(true);
        }}
      >
        New
      </button>
      <button
        type="button"
        className="btn secondary btn-sm"
        disabled={busy || loading || !projectId}
        onClick={openRenameForm}
        title="Rename the current project"
      >
        Rename
      </button>
      <button
        type="button"
        className="btn secondary btn-sm"
        disabled={busy || loading}
        onClick={() => void refreshProjects()}
        title="Refresh project list"
      >
        ↻
      </button>
      {error ? <span className="project-picker-error">{error}</span> : null}
    </div>
    {creating ? createPortal(
      <div
        className="folder-modal project-create-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-create-title"
        onClick={() => !busy && closeCreateForm()}
        onKeyDown={(event) => {
          if (event.key === "Escape" && !busy) closeCreateForm();
        }}
      >
        <form
          className="folder-modal-panel project-create-modal-panel"
          onClick={(event) => event.stopPropagation()}
          onSubmit={(event) => {
            event.preventDefault();
            void onCreate();
          }}
        >
          <div className="folder-modal-head">
            <div>
              <span className="mobile-eyebrow">New workspace</span>
              <h2 className="folder-modal-title" id="project-create-title">Create project</h2>
            </div>
          </div>
          {localError ? <div className="banner error">{localError}</div> : null}
          <div className="project-create-fields">
            <label className="field">
              <span>Project name</span>
              <input
                type="text"
                placeholder="Project name"
                value={newName}
                disabled={busy}
                autoFocus
                onChange={(event) => setNewName(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Mode</span>
              <select
                value={newMode}
                disabled={busy}
                onChange={(event) => setNewMode(event.target.value as ProjectMode)}
              >
                <option value="director">Director</option>
                <option value="json_production">JSON Production</option>
              </select>
            </label>
          </div>
          <div className="project-create-actions">
            <button type="button" className="btn secondary" disabled={busy} onClick={closeCreateForm}>
              Cancel
            </button>
            <button type="submit" className="btn primary" disabled={busy || !newName.trim()}>
              Create
            </button>
          </div>
        </form>
      </div>,
      document.body,
    ) : null}
    {renaming ? createPortal(
      <div
        className="folder-modal project-create-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-rename-title"
        onClick={() => !busy && closeRenameForm()}
        onKeyDown={(event) => {
          if (event.key === "Escape" && !busy) closeRenameForm();
        }}
      >
        <form
          className="folder-modal-panel project-create-modal-panel"
          onClick={(event) => event.stopPropagation()}
          onSubmit={(event) => {
            event.preventDefault();
            void onRename();
          }}
        >
          <div className="folder-modal-head">
            <div>
              <span className="mobile-eyebrow">Current project</span>
              <h2 className="folder-modal-title" id="project-rename-title">Rename project</h2>
            </div>
          </div>
          {localError ? <div className="banner error">{localError}</div> : null}
          <div className="project-create-fields">
            <label className="field">
              <span>Project name</span>
              <input
                type="text"
                placeholder="Project name"
                value={renameName}
                disabled={busy}
                autoFocus
                onChange={(event) => setRenameName(event.target.value)}
              />
            </label>
          </div>
          <div className="project-create-actions">
            <button type="button" className="btn secondary" disabled={busy} onClick={closeRenameForm}>
              Cancel
            </button>
            <button type="submit" className="btn primary" disabled={busy || !renameName.trim() || !projectId}>
              Save
            </button>
          </div>
        </form>
      </div>,
      document.body,
    ) : null}
    </>
  );
}
