import { useEffect, useState } from "react";
import { getDirectorPatrol, type DirectorPatrolStatus } from "./api";

function minutesAgo(iso: string | null): string {
  if (!iso) return "not yet";
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "not yet";
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (minutes < 1) return "just now";
  if (minutes === 1) return "1 minute ago";
  return `${minutes} minutes ago`;
}

export function MemoryPatrolStatus({ projectId }: { projectId: string }) {
  const [status, setStatus] = useState<DirectorPatrolStatus | null>(null);

  useEffect(() => {
    let active = true;
    const load = () => {
      getDirectorPatrol()
        .then((next) => {
          if (active) setStatus(next);
        })
        .catch(() => {
          if (active) setStatus(null);
        });
    };
    load();
    const timer = window.setInterval(load, 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [projectId]);

  if (!status?.enabled) return null;
  const project = status.projects[projectId];
  const count = project?.count ?? 0;
  const intervalMin = Math.round((status.interval_sec || 1800) / 60);

  return (
    <p className="director-soul-status" role="status">
      Memory check every {intervalMin} min. Last run {minutesAgo(status.last_run_at)}
      {count ? ` · ${count} open task${count === 1 ? "" : "s"}` : ""}.
    </p>
  );
}
