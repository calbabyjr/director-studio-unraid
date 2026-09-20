import { useEffect, useState } from "react";
import { getDirectorVramStatus } from "./api";
import { activityMeter, type ActivityKind } from "./generationStatus";

export function ActivityMeter() {
  const [label, setLabel] = useState("Activity · connecting to Director…");
  const [kind, setKind] = useState<ActivityKind>("idle");

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await getDirectorVramStatus();
        if (cancelled) return;
        const next = activityMeter(status, new Date());
        setKind(next.kind);
        setLabel(next.label);
      } catch {
        if (!cancelled) {
          setKind("idle");
          setLabel("Activity · Director status unreachable");
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

  return (
    <div
      className={`activity-meter activity-meter-${kind}`}
      role="status"
      aria-live="polite"
      title={label}
    >
      <span className="activity-meter-dot" aria-hidden="true" />
      <span className="activity-meter-label">{label}</span>
    </div>
  );
}
