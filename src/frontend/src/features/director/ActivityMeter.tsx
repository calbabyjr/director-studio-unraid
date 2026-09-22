import { useEffect, useState } from "react";
import { cancelDirectorChatSession, cancelDirectorJob, getDirectorVramStatus } from "./api";
import { activityMeter, type ActivityMeterState } from "./generationStatus";

const IDLE: ActivityMeterState = {
  kind: "idle",
  label: "Activity · connecting to Director…",
};

export function ActivityMeter() {
  const [state, setState] = useState<ActivityMeterState>(IDLE);
  const [cancelJobId, setCancelJobId] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await getDirectorVramStatus();
        if (cancelled) return;
        setState(activityMeter(status, new Date()));
        setCancelJobId(status.cancel_job_id || status.generation_jobs?.[0]?.job_id || null);
      } catch {
        if (!cancelled) {
          setState({
            kind: "idle",
            label: "Activity · Director status unreachable",
          });
        }
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const busy = state.kind === "comfy" || state.kind === "llm";
  const chatProjectIds = state.cancelChatProjectIds || [];
  const canCancel =
    (state.kind === "comfy" && Boolean(cancelJobId))
    || (state.kind === "llm" && chatProjectIds.length > 0);

  return (
    <div
      className={`activity-meter activity-meter-${state.kind}${busy ? " activity-meter-busy" : ""}`}
      role="status"
      aria-live="polite"
      title={state.label}
    >
      <span className="activity-meter-dot" aria-hidden="true" />
      <div className="activity-meter-copy">
        <span className="activity-meter-label">{state.label}</span>
      </div>
      {state.count ? (
        <span className="activity-meter-count">
          {state.count} {state.count === 1 ? "job" : "jobs"}
        </span>
      ) : null}
      {canCancel ? (
        <button
          type="button"
          className="btn ghost sm"
          disabled={cancelling}
          onClick={() => {
            setCancelling(true);
            void (async () => {
              if (chatProjectIds.length) {
                await Promise.all(
                  chatProjectIds.map((projectId) => cancelDirectorChatSession(projectId)),
                );
                return;
              }
              if (cancelJobId) {
                await cancelDirectorJob(cancelJobId);
              }
            })().finally(() => setCancelling(false));
          }}
        >
          {cancelling ? "Cancelling…" : "Cancel"}
        </button>
      ) : null}
    </div>
  );
}
