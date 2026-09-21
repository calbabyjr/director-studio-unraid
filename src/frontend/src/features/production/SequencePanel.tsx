import { useCallback, useEffect, useState } from "react";
import {
  assembleSequence,
  getSequence,
  sequenceExportUrl,
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
    return () => {
      cancelled = true;
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

  if (!projectId) return null;

  const errors = report?.issues.filter((issue) => issue.severity === "error") ?? [];
  const warnings = report?.issues.filter((issue) => issue.severity === "warning") ?? [];
  const canAssemble = (report?.clips_ready ?? 0) > 0;

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
            className="btn primary sm"
            disabled={busy || !canAssemble}
            onClick={() => void onAssemble()}
          >
            {busy ? "Assembling…" : "Assemble rough cut"}
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

      {error ? <div className="banner error">{error}</div> : null}

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
