import { useState } from "react";
import type { Shot } from "../../shared/api/types";
import { refreshShotPrompt } from "./api";

export const REFRESH_PROMPT_BUSY_LABEL = "Reviewing pictures…";

// Shared by the desktop Shot workspace and the mobile drawer for the
// "Prompt needs refresh" state.
export function useShotPromptRefresh(onUpdated?: (shot: Shot) => void) {
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [error, setError] = useState<{ shotId: string; message: string } | null>(null);

  const refresh = async (shotId: string) => {
    setRefreshingId(shotId);
    setError(null);
    try {
      onUpdated?.(await refreshShotPrompt(shotId));
    } catch (cause) {
      setError({ shotId, message: cause instanceof Error ? cause.message : String(cause) });
    } finally {
      setRefreshingId(null);
    }
  };

  return {
    refresh,
    refreshing: (shotId: string) => refreshingId === shotId,
    anyRefreshing: refreshingId !== null,
    errorFor: (shotId: string) => (error?.shotId === shotId ? error.message : ""),
  };
}
