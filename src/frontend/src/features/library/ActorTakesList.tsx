import { useEffect, useState } from "react";
import {
  listActorTakes,
  pinActorTake,
  type ActorTake,
  type LibraryAsset,
} from "./api";

export function ActorTakesList({
  actorId,
  busy = false,
  onPinned,
}: {
  actorId: string;
  busy?: boolean;
  onPinned?: (asset: LibraryAsset) => void;
}) {
  const [takes, setTakes] = useState<ActorTake[]>([]);
  const [pinningId, setPinningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    listActorTakes(actorId)
      .then((payload) => {
        if (!cancelled) setTakes(payload.items || []);
      })
      .catch((cause) => {
        if (cancelled) return;
        setTakes([]);
        setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, [actorId]);

  const onPin = async (jobId: string) => {
    setPinningId(jobId);
    setError(null);
    try {
      const updated = await pinActorTake(actorId, jobId);
      const payload = await listActorTakes(actorId);
      setTakes(payload.items || []);
      onPinned?.(updated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPinningId(null);
    }
  };

  return (
    <div className="takes-list" aria-label="Actor takes">
      <div className="takes-list-head">
        <strong>Takes</strong>
        <span className="muted tiny">{takes.length ? `${takes.length}` : "None"}</span>
      </div>
      <p className="muted tiny">Pin copies a generation’s outputs onto this actor.</p>
      {error ? <p className="field-error">{error}</p> : null}
      {takes.length === 0 && !error ? (
        <p className="muted tiny">No generation takes yet.</p>
      ) : (
        <div className="takes-list-items">
          {takes.map((take) => (
            <div key={take.id} className="takes-list-item muted tiny">
              <code title={take.id}>{take.id}</code>
              <span>{take.status}{take.pinned ? " · pinned" : ""}</span>
              {!take.pinned && take.status === "succeeded" ? (
                <button
                  type="button"
                  className="btn ghost sm"
                  disabled={busy || pinningId != null}
                  onClick={() => void onPin(take.id)}
                >
                  {pinningId === take.id ? "Pinning…" : "Pin"}
                </button>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
