import { useEffect, useState } from "react";
import { getDirectorVramStatus } from "./api";
import { activityMeter, type ActivityMeterState } from "./generationStatus";

const IDLE: ActivityMeterState = {
  kind: "idle",
  label: "Activity · connecting to Director…",
};

export function ActivityMeter() {
  const [state, setState] = useState<ActivityMeterState>(IDLE);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await getDirectorVramStatus();
        if (cancelled) return;
        setState(activityMeter(status, new Date()));
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
  const jobs = state.jobs || [];

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
        {jobs.length > 1 ? (
          <ul className="activity-meter-jobs">
            {jobs.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : null}
      </div>
      {state.count ? (
        <span className="activity-meter-count">
          {state.count} {state.count === 1 ? "job" : "jobs"}
        </span>
      ) : null}
    </div>
  );
}
