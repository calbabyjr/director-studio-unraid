import { useEffect, useState } from "react";
import { useProject } from "../../shared/project/ProjectContext";
import {
  createDirectorSoul,
  deleteDirectorSoul,
  listDirectorSouls,
  saveDirectorSoul,
  updateProject,
  type DirectorSoul,
} from "../director/api";

export function DirectorSoulSetup() {
  const { project, projectId, refreshProjects } = useProject();
  const [souls, setSouls] = useState<DirectorSoul[]>([]);
  const [selectedId, setSelectedId] = useState("studio");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [markdown, setMarkdown] = useState("");
  const [lessons, setLessons] = useState("");
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const selected = souls.find((soul) => soul.id === selectedId) || null;

  const load = async (preferId?: string) => {
    const next = await listDirectorSouls();
    setSouls(next);
    const pick = preferId && next.some((soul) => soul.id === preferId)
      ? preferId
      : project?.soul_id && next.some((soul) => soul.id === project.soul_id)
        ? project.soul_id
        : next[0]?.id || "studio";
    const soul = next.find((item) => item.id === pick) || next[0];
    if (!soul) return;
    setSelectedId(soul.id);
    setName(soul.name);
    setDescription(soul.description);
    setMarkdown(soul.markdown);
    setLessons(soul.lessons);
  };

  useEffect(() => {
    void load().catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [projectId]);

  const onSelect = (soulId: string) => {
    const soul = souls.find((item) => item.id === soulId);
    if (!soul) return;
    setSelectedId(soul.id);
    setName(soul.name);
    setDescription(soul.description);
    setMarkdown(soul.markdown);
    setLessons(soul.lessons);
    setStatus(null);
  };

  const onSave = async () => {
    if (!selected || busy) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await saveDirectorSoul(selected.id, {
        name,
        description,
        markdown,
        lessons,
      });
      setSouls((current) => current.map((soul) => soul.id === saved.id ? saved : soul));
      setStatus(`Saved ${saved.name}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const onCreate = async () => {
    const label = newName.trim();
    if (!label || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createDirectorSoul({ name: label });
      setNewName("");
      await load(created.id);
      setStatus(`Created ${created.name}. Edit soul.md below.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async () => {
    if (!selected || selected.builtin || busy) return;
    if (!window.confirm(`Delete soul “${selected.name}”? Projects using it should switch first.`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteDirectorSoul(selected.id);
      await load("studio");
      setStatus("Deleted custom soul.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const onUseForProject = async () => {
    if (!projectId || !selected || busy) return;
    setBusy(true);
    setError(null);
    try {
      await updateProject(projectId, { soul_id: selected.id });
      await refreshProjects();
      setStatus(`${selected.name} is now directing this project.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="director-soul-setup" aria-label="Director souls">
      <header>
        <div className="workspace-kicker">Director souls</div>
        <h2>Persona and learned craft</h2>
        <p>
          Each soul is a <code>soul.md</code> file you can edit. Create souls here even with no project open.
          Lessons accumulate as you correct the Director and carry into the next film that uses this soul.
        </p>
      </header>
      {error ? <div className="banner error">{error}</div> : null}
      {status ? <p className="director-soul-status" role="status">{status}</p> : null}

      <div className="director-soul-toolbar">
        <label>
          <span>Soul</span>
          <select aria-label="Edit soul" value={selectedId} onChange={(event) => onSelect(event.target.value)}>
            {souls.map((soul) => (
              <option key={soul.id} value={soul.id}>
                {soul.name}{soul.builtin ? "" : " (custom)"}
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
            <span>New soul</span>
            <input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="Horror director"
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
          <label>
            <span>Name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} disabled={busy} />
          </label>
          <label>
            <span>Description</span>
            <input value={description} onChange={(event) => setDescription(event.target.value)} disabled={busy} />
          </label>
          <label className="director-soul-markdown">
            <span>soul.md</span>
            <textarea
              aria-label="soul.md"
              value={markdown}
              onChange={(event) => setMarkdown(event.target.value)}
              rows={18}
              spellCheck={false}
              disabled={busy}
            />
          </label>
          <label className="director-soul-markdown">
            <span>Learned lessons (one bullet per line)</span>
            <textarea
              aria-label="Soul lessons"
              value={lessons}
              onChange={(event) => setLessons(event.target.value)}
              rows={8}
              spellCheck={false}
              disabled={busy}
              placeholder="- Keep performer identities exact"
            />
          </label>
          <div className="director-soul-actions">
            <button type="button" className="btn primary" disabled={busy} onClick={() => void onSave()}>
              Save soul
            </button>
            <button type="button" className="btn secondary" disabled={busy || !projectId} onClick={() => void onUseForProject()}>
              Use on this project
            </button>
            {!selected.builtin ? (
              <button type="button" className="btn danger" disabled={busy} onClick={() => void onDelete()}>
                Delete soul
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
