import { useEffect, useState } from "react";
import { getDirectorMemoryDocument, saveDirectorMemoryDocument } from "../director/api";

export function DirectorMemorySetup({
  soulId = null,
}: {
  soulId?: string | null;
}) {
  const [markdown, setMarkdown] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const document = await getDirectorMemoryDocument("global", null, soulId);
    setMarkdown(document.markdown);
  };

  useEffect(() => {
    void load().catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [soulId]);

  const onSave = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await saveDirectorMemoryDocument(markdown, "global", null, soulId);
      setStatus("Saved this director's MEMORY.md. Other directors do not read it.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="director-soul-setup workspace-files-setup" aria-label="Director memory">
      <header>
        <div className="workspace-kicker">Permanent memory</div>
        <h2>Director MEMORY.md</h2>
        <p>
          Lasting lessons for this directing soul only. The Director writes here after every
          turn, then rereads it on the next one. Other souls keep a separate MEMORY.md.
        </p>
      </header>
      {error ? <div className="banner error">{error}</div> : null}
      {status ? <p className="director-soul-status" role="status">{status}</p> : null}
      <label className="director-soul-markdown">
        <span>MEMORY.md</span>
        <textarea
          aria-label="MEMORY.md"
          value={markdown}
          onChange={(event) => setMarkdown(event.target.value)}
          rows={14}
          spellCheck={false}
          disabled={busy}
        />
      </label>
      <div className="director-soul-actions">
        <button type="button" className="btn primary" disabled={busy} onClick={() => void onSave()}>
          Save MEMORY.md
        </button>
      </div>
    </section>
  );
}
