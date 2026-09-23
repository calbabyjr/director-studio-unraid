import { useEffect, useState } from "react";
import { ChoiceChecklist } from "./ChoiceChecklist";
import {
  getScreenplayInterview,
  postScreenplayInterview,
  type ScreenplayInterviewState,
} from "./api";
import type { Project } from "../../shared/api/types";

export function ScreenplayInterviewPanel({
  project,
  disabled,
  onDrafted,
}: {
  project: Project;
  disabled?: boolean;
  onDrafted?: () => void;
}) {
  const locked = Boolean(project.script_locked);
  const hasScript = Boolean((project.script_text || "").trim());
  const [state, setState] = useState<ScreenplayInterviewState | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(!hasScript);

  useEffect(() => {
    if (locked || hasScript) return;
    let cancelled = false;
    setError(null);
    void getScreenplayInterview(project.id)
      .then((next) => {
        if (!cancelled) setState(next);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [project.id, locked, hasScript]);

  if (locked || hasScript) return null;

  const run = async (body: { message?: string; generate?: boolean; reset?: boolean }) => {
    setBusy(true);
    setError(null);
    try {
      const next = await postScreenplayInterview(project.id, body);
      setState(next);
      setDraft("");
      if (next.drafted) {
        setExpanded(false);
        onDrafted?.();
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const turns = state?.turns || [];
  const canWrite = Boolean((state?.premise || draft).trim());

  return (
    <section
      className={`script-draft-panel screenplay-interview${expanded ? "" : " is-collapsed"}`}
      aria-label="Screenplay interview"
    >
      <header className="script-draft-head">
        <button
          type="button"
          className="script-draft-toggle"
          aria-expanded={expanded}
          aria-label={expanded ? "Hide screenplay interview" : "Show screenplay interview"}
          onClick={() => setExpanded((open) => !open)}
        >
          <span className="muted tiny">
            {state?.ready ? "Ready to write pages" : "Screenplay interview"}
          </span>
          <h3>{hasScript ? "Develop a new draft" : "Build the screenplay"}</h3>
        </button>
        <div className="script-draft-actions">
          <button
            type="button"
            className="btn primary sm"
            disabled={disabled || busy || !canWrite}
            onClick={() => void run({ generate: true, message: draft.trim() || undefined })}
          >
            {busy ? "Working…" : "Write the screenplay"}
          </button>
        </div>
      </header>
      {expanded ? (
        <>
          <p className="muted tiny">
            Drop in an idea. The writer asks follow-ups, then writes Fountain pages you can lock.
          </p>
          {turns.length ? (
            <ol className="screenplay-interview-log">
              {turns.map((turn, index) => {
                const latestChoices = index === turns.length - 1 && turn.role === "assistant" ? turn.choices : undefined;
                return (
                <li key={`${turn.role}-${index}`} className={`screenplay-interview-turn is-${turn.role}`}>
                  <span className="muted tiny">{turn.role === "user" ? "You" : "Writer"}</span>
                  <p>{turn.content}</p>
                  {latestChoices?.length ? (
                    <ChoiceChecklist
                      questions={latestChoices}
                      disabled={disabled || busy}
                      onSubmit={(text) => void run({ message: text })}
                    />
                  ) : null}
                </li>
                );
              })}
            </ol>
          ) : null}
          <label className="screenplay-interview-input">
            <span className="muted tiny">{turns.length ? "Your answer" : "Your ideas"}</span>
            <textarea
              value={draft}
              disabled={disabled || busy}
              placeholder={
                turns.length
                  ? "Answer the writer, or add another detail."
                  : "Who is this about, what happens, what tone, how long?"
              }
              aria-label={turns.length ? "Interview answer" : "Screenplay ideas"}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && draft.trim()) {
                  event.preventDefault();
                  void run({ message: draft.trim() });
                }
              }}
            />
          </label>
          <div className="script-draft-actions">
            <button
              type="button"
              className="btn secondary sm"
              disabled={disabled || busy || !draft.trim()}
              onClick={() => void run({ message: draft.trim() })}
            >
              {turns.length ? "Send answer" : "Start interview"}
            </button>
            {turns.length ? (
              <button
                type="button"
                className="btn ghost sm"
                disabled={disabled || busy}
                onClick={() => void run({ reset: true })}
              >
                Start over
              </button>
            ) : null}
          </div>
        </>
      ) : null}
      {error ? <p className="field-error">{error}</p> : null}
    </section>
  );
}
