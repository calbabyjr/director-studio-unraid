import { useCallback, useEffect, useState } from "react";

const STORAGE_PREFIX = "ds.directorChatQueue.";

export interface QueuedChatImage {
  file: File;
  previewUrl: string;
}

export interface QueuedChatMessage {
  id: string;
  text: string;
  images: QueuedChatImage[];
}

function storageKey(projectId: string) {
  return `${STORAGE_PREFIX}${projectId}`;
}

// Only text items survive a refresh; File objects cannot be serialized.
function loadStoredQueue(projectId: string): QueuedChatMessage[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(storageKey(projectId)) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((item) =>
      item && typeof item.id === "string" && typeof item.text === "string" && item.text
        ? [{ id: item.id, text: item.text, images: [] }]
        : [],
    );
  } catch {
    return [];
  }
}

function storeQueue(projectId: string, items: QueuedChatMessage[]) {
  try {
    const textOnly = items
      .filter((item) => item.images.length === 0)
      .map(({ id, text }) => ({ id, text }));
    if (textOnly.length) localStorage.setItem(storageKey(projectId), JSON.stringify(textOnly));
    else localStorage.removeItem(storageKey(projectId));
  } catch {
    // Storage unavailable: the queue still works in memory.
  }
}

function revokeImages(items: QueuedChatMessage[]) {
  for (const item of items) {
    for (const image of item.images) URL.revokeObjectURL(image.previewUrl);
  }
}

/**
 * Per-project queue of Director chat messages typed while a turn is running.
 * Keyed by project id so switching projects shows that project's queue.
 */
export function useDirectorChatQueue(projectId: string | null) {
  const [queues, setQueues] = useState<Record<string, QueuedChatMessage[]>>({});

  useEffect(() => {
    if (!projectId) return;
    setQueues((all) => (projectId in all ? all : { ...all, [projectId]: loadStoredQueue(projectId) }));
  }, [projectId]);

  const update = useCallback(
    (targetId: string, change: (items: QueuedChatMessage[]) => QueuedChatMessage[]) => {
      setQueues((all) => {
        const next = change(all[targetId] ?? loadStoredQueue(targetId));
        storeQueue(targetId, next);
        return { ...all, [targetId]: next };
      });
    },
    [],
  );

  const enqueue = useCallback((targetId: string, text: string, images: QueuedChatImage[]) => {
    const item = { id: `queued-${Date.now()}-${Math.random().toString(36).slice(2)}`, text, images };
    update(targetId, (items) => [...items, item]);
  }, [update]);

  const remove = useCallback((targetId: string, id: string) => {
    update(targetId, (items) => {
      revokeImages(items.filter((item) => item.id === id));
      return items.filter((item) => item.id !== id);
    });
  }, [update]);

  const clear = useCallback((targetId: string) => {
    update(targetId, (items) => {
      revokeImages(items);
      return [];
    });
  }, [update]);

  // Dispatch helpers: take leaves image previews alive for the sent chat bubble.
  const take = useCallback((targetId: string, id: string) => {
    update(targetId, (items) => items.filter((item) => item.id !== id));
  }, [update]);

  const restoreHead = useCallback((targetId: string, item: QueuedChatMessage) => {
    update(targetId, (items) => (items.some((candidate) => candidate.id === item.id) ? items : [item, ...items]));
  }, [update]);

  return {
    items: projectId ? queues[projectId] ?? [] : [],
    enqueue,
    remove,
    clear,
    take,
    restoreHead,
  };
}
