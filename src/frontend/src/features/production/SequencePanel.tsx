import { useCallback, useEffect, useRef, useState } from "react";
import {
  assembleSequence,
  cancelProductionQueue,
  getProductionQueue,
  getSequence,
  sequenceExportUrl,
  startProductionQueue,
  type ProductionQueue,
  type SequenceClipStatus,
  type SequenceReport,
} from "./sequenceApi";

const CLIP_LABEL: Record<SequenceClipStatus, string> = {
  ready: "clip ready",
  missing: "no clip",
  failed: "clip failed",
  running: "generating",
};

export function SequencePanel({
  projectId,
  active = true,
  mobile = false,
  onSelectShot,
}: {
  projectId: string | null;
  active?: boolean;
  mobile?: boolean;
  onSelectShot?: (shotId: string) => void;
}) {
  const [report, setReport] = useState<SequenceReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [queue, setQueue] = useState<ProductionQueue | null>(null);
  const [chainTailFrames, setChainTailFrames] = useState(true);
  const assemblingRef = useRef(false);
  const assembleAttemptRef = useRef("");

  const refresh = useCallback(async (id: string) => {
    const next = await getSequence(id);
    setReport(next);
    setError(null);
    return next;
  }, []);

  useEffect(() => {
    if (!active || !projectId) {
      setReport(null);
      setError(null);
      return;
    }
    let cancelled = false;
    const tick = () => {
      getSequence(projectId)
        .then((next) => {
          if (!cancelled) {
            setReport(next);
            setError(null);
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setReport(null);
            setError(err instanceof Error ? err.message : String(err));
          }
        });
    };
    tick();
    const timer = window.setInterval(tick, 3000);
    const pollQueue = () => {
      getProductionQueue(projectId)
        .then((next) => {
          if (!cancelled) setQueue(next);
        })
        .catch(() => undefined);
    };
    pollQueue();
    const queueTimer = window.setInterval(pollQueue, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.clearInterval(queueTimer);
    };
  }, [active, projectId]);

  const onAssemble = async () => {
    if (!projectId || busy) return;
    setBusy(true);
    setError(null);
    try {
      await assembleSequence(projectId);
      await refresh(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const errors = report?.issues.filter((issue) => issue.severity === "error") ?? [];
  const warnings = report?.issues.filter((issue) => issue.severity === "warning") ?? [];
  const canAssemble = (report?.clips_ready ?? 0) > 0;
  const readyJobIds = (report?.shots ?? [])
    .filter((shot) => shot.clip_status === "ready" && shot.clip_job_id)
    .map((shot) => shot.clip_job_id as string);
  const assembledJobIds = report?.last_assembly?.clip_job_ids ?? [];
  const readyJobSignature = readyJobIds.join("|");
  const assemblyStale =
    Boolean(report?.last_assembly)
    && readyJobSignature !== assembledJobIds.join("|");

  useEffect(() => {
    if (!active || !projectId || !assemblyStale || assemblingRef.current) return;
    if (assembleAttemptRef.current === readyJobSignature) return;
    assemblingRef.current = true;
    assembleAttemptRef.current = readyJobSignature;
    setBusy(true);
    assembleSequence(projectId)
      .then(() => refresh(projectId))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => {
        assemblingRef.current = false;
        setBusy(false);
      });
  }, [active, assemblyStale, projectId, readyJobSignature, refresh]);

  if (!projectId) return null;

  return (
    <section
      className={`sequence-panel section-card${mobile ? " sequence-panel-mobile" : ""}`}
      aria-label="Sequence"
    >
      <div className="section-card-head sequence-panel-head">
        <div>
          <h2 className="section-card-title">Sequence</h2>
          <p className="muted tiny">
            {report
              ? `${report.shot_count} shots · ${report.scene_count} scenes · ${report.runtime} planned · ${report.clips_ready} clips ready`
              : "Runtime, continuity, and rough cut"}
          </p>
        </div>
        <div className="sequence-actions">
          <button
            type="button"
            className="btn secondary sm"
            disabled={busy || queue?.status === "running"}
            onClick={() => {
              if (!projectId) return;
              const nextId = report?.shots.find((shot) => shot.clip_status !== "ready")?.shot_id;
              void startProductionQueue(projectId, {
                mode: "next",
                from_shot_id: nextId || null,
                chain_tail_frames: chainTailFrames,
              })
                .then(setQueue)
                .catch((err) => setError(err instanceof Error ? err.message : String(err)));
            }}
          >
            Run next
          </button>
          <button
            type="button"
            className="btn secondary sm"
            disabled={busy || queue?.status === "running"}
            onClick={() => {
              if (!projectId) return;
              const nextId = report?.shots.find((shot) => shot.clip_status !== "ready")?.shot_id;
              void startProductionQueue(projectId, {
                mode: "remaining",
                from_shot_id: nextId || null,
                chain_tail_frames: chainTailFrames,
              })
                .then(setQueue)
                .catch((err) => setError(err instanceof Error ? err.message : String(err)));
            }}
          >
            Run remaining
          </button>
          {queue?.status === "running" ? (
            <button
              type="button"
              className="btn ghost sm"
              onClick={() => {
                if (!projectId) return;
                void cancelProductionQueue(projectId)
                  .then(setQueue)
                  .catch((err) => setError(err instanceof Error ? err.message : String(err)));
              }}
            >
              Stop queue
            </button>
          ) : null}
          <button
            type="button"
            className="btn primary sm"
            disabled={busy || !canAssemble}
            onClick={() => void onAssemble()}
          >
            {busy ? "Updating…" : assemblyStale ? "Update rough cut" : "Assemble rough cut"}
          </button>
          <a className="btn secondary sm" href={sequenceExportUrl(projectId, "srt")}>
            SRT
          </a>
          <a className="btn secondary sm" href={sequenceExportUrl(projectId, "edl")}>
            EDL
          </a>
          <a className="btn secondary sm" href={sequenceExportUrl(projectId, "csv")}>
            Shot list
          </a>
        </div>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={chainTailFrames}
          disabled={busy || queue?.status === "running"}
          onChange={(event) => setChainTailFrames(event.target.checked)}
        />
        <span>Chain tail frame into next shot</span>
      </label>

      {queue?.status === "running" ? (
        <p className="muted tiny" role="status">
          Queue {queue.mode} · current {queue.current_shot_id || "—"} · {queue.pending_shot_ids.length} waiting
        </p>
      ) : null}
      {queue?.status === "failed" && queue.error ? (
        <div className="banner error">{queue.error}</div>
      ) : null}

      {error ? <div className="banner error">{error}</div> : null}

      {assemblyStale ? (
        <p className="muted tiny" role="status">
          New clips since the last rough cut
          {readyJobIds.length ? ` · ${readyJobIds.length} ready` : ""}. Updating…
        </p>
      ) : null}

      {report?.last_assembly ? (
        <div className="sequence-assembly">
          <video
            className="sequence-assembly-video"
            src={`${report.last_assembly.url}?t=${encodeURIComponent(report.last_assembly.created_at)}`}
            controls
            playsInline
            aria-label="Rough cut"
          />
          <p className="muted tiny">
            Rough cut
            {report.last_assembly.duration_s
              ? ` · ${Math.round(report.last_assembly.duration_s)}s`
              : ""}
            {report.last_assembly.missing_shot_ids.length
              ? ` · skipped ${report.last_assembly.missing_shot_ids.length} shot(s) without clips`
              : ""}
          </p>
        </div>
      ) : null}

      {report?.shots.length ? (
        <ol className="sequence-timeline" aria-label="Shot timeline">
          {report.shots.map((shot) => (
            <li key={shot.shot_id}>
              <button
                type="button"
                className={`sequence-beat clip-${shot.clip_status}`}
                title={`${shot.title} · ${CLIP_LABEL[shot.clip_status]}`}
                onClick={() => onSelectShot?.(shot.shot_id)}
              >
                <span className="sequence-beat-index">
                  {String(shot.index).padStart(2, "0")}
                </span>
                <span className="sequence-beat-title">{shot.title || shot.shot_id}</span>
                <span className="muted tiny">{shot.duration_s}s</span>
              </button>
            </li>
          ))}
        </ol>
      ) : null}

      {errors.length || warnings.length ? (
        <ul className="sequence-issues" aria-label="Continuity issues">
          {report?.issues.slice(0, mobile ? 6 : 10).map((issue, index) => (
            <li key={`${issue.shot_id}-${issue.code}-${index}`}>
              <button
                type="button"
                className={`sequence-issue sequence-issue-${issue.severity}`}
                onClick={() => onSelectShot?.(issue.shot_id)}
              >
                <span>{issue.severity === "error" ? "Error" : "Note"}</span>
                {issue.message}
              </button>
            </li>
          ))}
        </ul>
      ) : report && report.shot_count > 0 ? (
        <p className="muted tiny">No continuity flags on the current cut.</p>
      ) : null}
    </section>
  );
}
