import { useEffect, useState } from "react";
import { useProject } from "../../shared/project/ProjectContext";
import {
  createWorkspaceFile,
  deleteWorkspaceFile,
  listWorkspaceFiles,
  saveWorkspaceFile,
  type WorkspaceFile,
  type WorkspaceScope,
} from "../director/api";

export function WorkspaceFilesSetup({
  scope,
  soulId = null,
}: {
  scope: WorkspaceScope;
  soulId?: string | null;
}) {
  const { projectId } = useProject();
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [selectedName, setSelectedName] = useState("AGENTS.md");
  const [markdown, setMarkdown] = useState("");
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const needsProject = scope === "project";
  const ready = !needsProject || Boolean(projectId);
  const activeProjectId = needsProject ? projectId : null;
  const selected = files.find((item) => item.name === selectedName) || null;
  const extras = files.filter((item) => item.name.toLowerCase() !== "user.md");

  const load = async (preferName?: string) => {
    if (needsProject && !projectId) {
      setFiles([]);
      setMarkdown("");
      return;
    }
    const next = await listWorkspaceFiles(scope, activeProjectId, soulId);
    const visible = next.filter((item) => item.name.toLowerCase() !== "user.md");
    setFiles(visible);
    const pick = preferName && visible.some((item) => item.name === preferName)
      ? preferName
      : visible.find((item) => item.name === selectedName)?.name
        || visible[0]?.name
        || "AGENTS.md";
    const current = visible.find((item) => item.name === pick) || visible[0];
    if (!current) {
      setSelectedName("AGENTS.md");
      setMarkdown("");
      return;
    }
    setSelectedName(current.name);
    setMarkdown(current.markdown);
  };

  useEffect(() => {
    void load().catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [scope, projectId, soulId]);

  const onSelect = (name: string) => {
    const item = files.find((file) => file.name === name);
    if (!item) return;
    setSelectedName(item.name);
    setMarkdown(item.markdown);
    setStatus(null);
  };

  const onSave = async () => {
    if (!selected || busy || !ready) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await saveWorkspaceFile(selected.name, markdown, scope, activeProjectId, soulId);
      setFiles((current) => current.map((item) => item.name === saved.name ? saved : item));
      setStatus(`Saved ${saved.name}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const onCreate = async () => {
    const label = newName.trim();
    if (!label || busy || !ready) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createWorkspaceFile({
        name: label,
        scope,
        projectId: activeProjectId,
        soulId,
      });
      setNewName("");
      await load(created.name);
      setStatus(`Created ${created.name}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async () => {
    if (!selected || selected.reserved || busy || !ready) return;
    if (!window.confirm(`Delete ${selected.name}? The Director will stop loading it.`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteWorkspaceFile(selected.name, scope, activeProjectId, soulId);
      await load("AGENTS.md");
      setStatus(`Deleted ${selected.name}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const title = scope === "global" ? "This director's workspace" : "This production";
  const kicker = scope === "global" ? "Director workspace" : "Project workspace";
  const copy = scope === "global"
    ? "Markdown this directing soul loads on every production it leads. Other directors keep their own files."
    : "Markdown the Director loads only for the open project. Project files outrank this director's workspace files when they conflict.";

  return (
    <section className="director-soul-setup workspace-files-setup" aria-label={title}>
      <header>
        <div className="workspace-kicker">{kicker}</div>
        <h2>{title}</h2>
        <p>{copy}</p>
      </header>
      {needsProject && !projectId ? (
        <p className="director-soul-status">Open a project to edit this production's workspace files.</p>
      ) : null}
      {error ? <div className="banner error">{error}</div> : null}
      {status ? <p className="director-soul-status" role="status">{status}</p> : null}

      {ready ? (
        <>
          <div className="director-soul-toolbar">
            <label>
              <span>File</span>
              <select
                aria-label="Edit workspace file"
                value={selectedName}
                onChange={(event) => onSelect(event.target.value)}
              >
                {extras.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}{item.reserved ? "" : " (extra)"}
                  </option>
                ))}
              </select>
            </label>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void onCreate();
              }}
            >
              <label>
                <span>New file</span>
                <input
                  value={newName}
                  onChange={(event) => setNewName(event.target.value)}
                  placeholder="house-style.md"
                  disabled={busy}
                />
              </label>
              <button type="submit" className="btn secondary" disabled={busy || !newName.trim()}>
                Create
              </button>
            </form>
          </div>

          {selected ? (
            <div className="director-soul-editor">
              <label className="director-soul-markdown">
                <span>{selected.name}</span>
                <textarea
                  aria-label={selected.name}
                  value={markdown}
                  onChange={(event) => setMarkdown(event.target.value)}
                  rows={14}
                  spellCheck={false}
                  disabled={busy}
                />
              </label>
              <div className="director-soul-actions">
                <button type="button" className="btn primary" disabled={busy} onClick={() => void onSave()}>
                  Save {selected.name}
                </button>
                {!selected.reserved ? (
                  <button type="button" className="btn danger" disabled={busy} onClick={() => void onDelete()}>
                    Delete file
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
