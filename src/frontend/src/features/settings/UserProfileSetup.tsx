import { useEffect, useState } from "react";
import { saveWorkspaceFile, listWorkspaceFiles } from "../director/api";

export function UserProfileSetup() {
  const [markdown, setMarkdown] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const files = await listWorkspaceFiles("global");
    const user = files.find((item) => item.name.toLowerCase() === "user.md");
    setMarkdown(user?.markdown || "");
  };

  useEffect(() => {
    void load().catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, []);

  const onSave = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await saveWorkspaceFile("user.md", markdown, "global");
      setStatus("Saved user.md. The Director will read it on the next turn.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="director-soul-setup workspace-files-setup" aria-label="User profile">
      <header>
        <div className="workspace-kicker">You</div>
        <h2>user.md</h2>
        <p>
          Who you are and how you like the Director to work with you. This file is studio-wide:
          every production reads it. Leave the template empty of real facts until you write them.
        </p>
      </header>
      {error ? <div className="banner error">{error}</div> : null}
      {status ? <p className="director-soul-status" role="status">{status}</p> : null}
      <label className="director-soul-markdown">
        <span>user.md</span>
        <textarea
          aria-label="user.md"
          value={markdown}
          onChange={(event) => setMarkdown(event.target.value)}
          rows={12}
          spellCheck={false}
          disabled={busy}
        />
      </label>
      <div className="director-soul-actions">
        <button type="button" className="btn primary" disabled={busy} onClick={() => void onSave()}>
          Save user.md
        </button>
      </div>
    </section>
  );
}
