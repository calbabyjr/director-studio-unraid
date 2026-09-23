import { useCallback, useEffect, useRef, useState } from "react";
import {
  layoutPreviewUrl,
  type Shot,
} from "../../shared/api/types";
import { ResizableWorkspace } from "../../shared/components/ResizableWorkspace";
import { useProject } from "../../shared/project/ProjectContext";
import { ShotWorkspace } from "./ShotWorkspace";
import { ContextUsagePanel } from "./ContextUsage";
import { ContextCompaction } from "./ContextCompaction";
import { MemoryNotes } from "./MemoryNotes";
import { ScriptDraftPanel } from "./ScriptDraftPanel";
import { ScreenplayInterviewPanel } from "./ScreenplayInterviewPanel";
import { MemoryPatrolStatus } from "./MemoryPatrolStatus";
import { MobileShotDrawer } from "./MobileShotDrawer";
import { firstActionableShotId, shotWorkflowStatus } from "../../shared/shotWorkflowStatus";
import { ChoiceChecklist, parseChoiceQuestionsFromText } from "./ChoiceChecklist";
import {
  cancelDirectorChatSession,
  DirectorChatError,
  chatWithDirectorStream,
  getDirectorChatHistory,
  getDirectorChatSession,
  getDirectorModel,
  getDirectorVramStatus,
  getProject,
  listDirectorSouls,
  setDirectorModel,
  updateProject,
  type DirectorSoul,
  type ChatMessage,
  type ContextUsage,
  type DirectorChatSessionStatus,
} from "./api";
import {
  generationStatusText,
  type DirectorVramStatus,
} from "./generationStatus";
import { useDirectorChatQueue, type QueuedChatMessage } from "./useDirectorChatQueue";

const MAX_CHAT_IMAGES = 4;
const MAX_CHAT_IMAGE_BYTES = 20 * 1024 * 1024;
const CHAT_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const IDLE_CHAT_SESSION: DirectorChatSessionStatus = {
  active: false,
  session_id: null,
  started_at: null,
};

interface PendingChatImage {
  file: File;
  previewUrl: string;
}

type SendResult = "sent" | "queued" | "failed" | "cancelled" | "skipped";

function layoutChatEntries(shot: Shot) {
  const layouts = shot.layout_refs;
  if (layouts.length) {
    const submittedLayoutAssets = new Set(
      shot.refs
        .filter((ref) => ref.role === "layout_ref_frame")
        .map((ref) => ref.asset_id),
    );
    if (submittedLayoutAssets.size === 0 && shot.layout_asset_id) {
      submittedLayoutAssets.add(shot.layout_asset_id);
    }
    return layouts.flatMap((layout) => {
      if (!layout.asset_id) return [];
      if (!submittedLayoutAssets.has(layout.asset_id)) return [];
      if (layout.review_status === "reject") return [];
      if (layout.superseded_by) return [];
      const url = layoutPreviewUrl(layout.asset_id);
      return url
        ? [{ key: `${layout.id}:${layout.asset_id}`, assetId: layout.asset_id, url, purpose: layout.purpose }]
        : [];
    });
  }
  if (!shot.layout_asset_id) return [];
  const url = layoutPreviewUrl(shot.layout_asset_id);
  return url ? [{ key: `legacy:${shot.layout_asset_id}`, assetId: shot.layout_asset_id, url, purpose: "reference frame" }] : [];
}

function visibleChatImages(images: ChatMessage["images"], shots: Shot[]) {
  return (images ?? []).filter((image) => {
    if (!image.shot_id || !image.url.includes("/api/files/library/layouts/")) {
      return true;
    }
    const shot = shots.find((candidate) => candidate.id === image.shot_id);
    if (!shot) return false;
    return layoutChatEntries(shot).some((entry) => entry.url === image.url);
  });
}

function ChatImageCard({
  url,
  caption,
  onOpen,
}: {
  url: string;
  caption?: string;
  onOpen: (url: string) => void;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <button
      type="button"
      className="chat-image-btn"
      onClick={() => onOpen(url)}
      title={caption || "preview"}
    >
      <img
        src={url}
        alt={caption || "layout"}
        onError={() => setFailed(true)}
      />
      {caption ? <span className="chat-image-cap">{caption}</span> : null}
    </button>
  );
}

function shouldPollShot(shot: Shot): boolean {
  if (["failed", "blocked"].includes(shot.status)) return false;
  const unresolvedLayout = shot.layout_refs.some(
    (layout) =>
      Boolean(layout.job_id) &&
      !layout.asset_id &&
      layout.job_status !== "failed" &&
      layout.job_status !== "cancelled",
  );
  // ref_frame_pending with no in-flight Layout job is idle (waiting on Director),
  // not a running worker. Polling that state hammers GET /api/projects forever.
  return unresolvedLayout || ["planning", "queued", "running"].includes(shot.status);
}

function shotPollSignature(shots: Shot[]): string {
  return shots
    .map((shot) => {
      const layouts = shot.layout_refs
        .map((layout) => `${layout.id}:${layout.job_id || ""}:${layout.job_status || ""}:${layout.asset_id || ""}`)
        .join(",");
      return `${shot.id}:${shot.status}:${shot.h3_job_id || ""}:${layouts}`;
    })
    .join("|");
}

function JsonModeDirectorNotice() {
  return (
    <main className="workspace">
      <section className="panel">
        <h2>Director</h2>
        <p>This project bypasses the local Director Agent</p>
        <p className="muted">
          Use the Production tab to import storyboard JSON and submit shots directly to H3.
        </p>
      </section>
    </main>
  );
}

/**
 * Chat-first Director: natural language + optional short command chips.
 * Shot cards on the right show layout previews and refresh with project state.
 */
export interface DirectorChatRequest {
  id: string;
  projectId: string;
  message: string;
}

export function DirectorPage({
  chatOnly = false,
  mobile = false,
  requestedMessage = null,
  active = true,
}: {
  chatOnly?: boolean;
  mobile?: boolean;
  requestedMessage?: DirectorChatRequest | null;
  active?: boolean;
} = {}) {
  const { project } = useProject();
  if (project?.mode === "json_production") {
    return <JsonModeDirectorNotice />;
  }
  return (
    <DirectorAgentWorkspace
      chatOnly={chatOnly}
      mobile={mobile}
      requestedMessage={requestedMessage}
      active={active}
    />
  );
}

function DirectorAgentWorkspace({
  chatOnly,
  mobile,
  requestedMessage,
  active,
}: {
  chatOnly: boolean;
  mobile: boolean;
  requestedMessage: DirectorChatRequest | null;
  active: boolean;
}) {
  const { project, projectId, refreshProjects, createAndSelect } = useProject();
  const [shots, setShots] = useState<Shot[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [pendingImages, setPendingImages] = useState<PendingChatImage[]>([]);
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [vramPollError, setVramPollError] = useState<string | null>(null);
  const [vramStatus, setVramStatus] = useState<DirectorVramStatus | null>(null);
  const [clockNow, setClockNow] = useState(() => new Date());
  const [busy, setBusy] = useState(false);
  const [lightbox, setLightbox] = useState<string | null>(null);
  const [liveStatus, setLiveStatus] = useState<string[]>([]);
  const [liveRuntime, setLiveRuntime] = useState("");
  const [liveThink, setLiveThink] = useState("");
  const [liveTokens, setLiveTokens] = useState("");
  const [contextUsage, setContextUsage] = useState<ContextUsage[]>([]);
  const [compactingContext, setCompactingContext] = useState(false);
  const [llmModel, setLlmModel] = useState<string>("");
  const [llmOptions, setLlmOptions] = useState<string[]>([]);
  const [llmProvider, setLlmProvider] = useState("LLM provider");
  const [llmReachable, setLlmReachable] = useState(false);
  const [llmBusy, setLlmBusy] = useState(false);
  const [souls, setSouls] = useState<DirectorSoul[]>([]);
  const [soulBusy, setSoulBusy] = useState(false);
  const [chatSession, setChatSession] = useState<DirectorChatSessionStatus>(IDLE_CHAT_SESSION);
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null);
  const chatAbortRef = useRef<AbortController | null>(null);
  const usageProjectRef = useRef(projectId);
  usageProjectRef.current = projectId;
  const chatLogRef = useRef<HTMLDivElement | null>(null);
  const [stickToBottom, setStickToBottom] = useState(true);
  const seenLayouts = useRef<Set<string>>(new Set());
  const shotRevision = useRef(0);
  const lastPollSignature = useRef("");
  const handledRequestId = useRef<string | null>(null);
  const generationLocked = vramStatus?.chat_locked === true;
  const chatActive = chatSession.active;
  const chatBusy = busy || compactingContext || generationLocked || chatActive;
  const chatDisabled = chatBusy || !llmModel;
  // While a turn runs, the composer stays editable and new messages queue up.
  const canQueue = chatBusy && Boolean(projectId) && Boolean(llmModel);
  const composerDisabled = chatDisabled && !canQueue;
  const chatQueue = useDirectorChatQueue(projectId);
  const [queuePaused, setQueuePaused] = useState(false);
  const [dispatchTick, setDispatchTick] = useState(0);
  const dispatchingRef = useRef(false);

  const addChatImages = (files: FileList | null) => {
    if (!files?.length) return;
    const available = MAX_CHAT_IMAGES - pendingImages.length;
    const selected = Array.from(files).slice(0, available);
    const invalid = selected.find(
      (file) => !CHAT_IMAGE_TYPES.has(file.type) || file.size > MAX_CHAT_IMAGE_BYTES,
    );
    if (invalid) {
      setError(
        CHAT_IMAGE_TYPES.has(invalid.type)
          ? `${invalid.name} exceeds the 20 MB image limit.`
          : `${invalid.name} is not a supported JPG, PNG, or WebP image.`,
      );
      return;
    }
    if (files.length > available) {
      setError(`Director chat accepts at most ${MAX_CHAT_IMAGES} images.`);
    } else {
      setError(null);
    }
    setPendingImages((current) => [
      ...current,
      ...selected.map((file) => ({ file, previewUrl: URL.createObjectURL(file) })),
    ]);
  };

  const removeChatImage = (index: number) => {
    setPendingImages((current) => {
      const removed = current[index];
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return current.filter((_, candidateIndex) => candidateIndex !== index);
    });
  };

  const replaceShots = useCallback((nextShots: Shot[]) => {
    shotRevision.current += 1;
    lastPollSignature.current = shotPollSignature(nextShots);
    setShots(nextShots);
  }, []);

  useEffect(() => {
    setSelectedShotId((current) =>
      current && shots.some((shot) => shot.id === current)
        ? current
        : shots[0]?.id ?? null,
    );
  }, [shots]);

  const loadLlmModels = useCallback(async () => {
    try {
      const st = await getDirectorModel();
      setLlmModel(st.model || "");
      setLlmProvider(st.provider || "LLM provider");
      setLlmReachable(st.reachable !== false);
      setLlmOptions([...(st.available || [])]);
    } catch {
      setLlmReachable(false);
      setLlmOptions([]);
    }
  }, []);

  useEffect(() => {
    void listDirectorSouls().then(setSouls).catch(() => setSouls([]));
  }, []);

  const onChangeSoul = async (soulId: string) => {
    if (!projectId || soulBusy) return;
    setSoulBusy(true);
    try {
      await updateProject(projectId, { soul_id: soulId });
      await refreshProjects();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSoulBusy(false);
    }
  };

  useEffect(() => {
    void loadLlmModels();
  }, [loadLlmModels]);

  const refreshVramStatus = useCallback(async () => {
    try {
      const status = await getDirectorVramStatus();
      setVramStatus(status);
      setClockNow(new Date());
      setVramPollError(null);
    } catch (cause) {
      setVramPollError(
        `Could not refresh generation status: ${cause instanceof Error ? cause.message : String(cause)}`,
      );
    }
  }, []);

  useEffect(() => {
    if (!projectId) {
      setVramStatus(null);
      setVramPollError(null);
      return;
    }
    if (!active && !chatActive) return;
    void refreshVramStatus();
    const timer = window.setInterval(() => void refreshVramStatus(), 2500);
    return () => window.clearInterval(timer);
  }, [projectId, active, chatActive, refreshVramStatus]);

  useEffect(() => {
    if (!active || !generationLocked) return;
    const timer = window.setInterval(() => setClockNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, [active, generationLocked]);

  const onChangeLlm = async (model: string) => {
    if (!model || model === llmModel) return;
    setLlmBusy(true);
    setError(null);
    try {
      const st = await setDirectorModel(model, true);
      setLlmModel(st.model);
      setContextUsage([]);
      if (st.available?.length) setLlmOptions(st.available);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLlmBusy(false);
    }
  };

  const loadProject = useCallback(async (id: string) => {
    const detail = await getProject(id);
    replaceShots(detail.shots);
    return detail;
  }, [replaceShots]);

  useEffect(() => {
    if (!shots.length) {
      setSelectedShotId(null);
      return;
    }
    setSelectedShotId((current) =>
      current && shots.some((shot) => shot.id === current)
        ? current
        : firstActionableShotId(shots),
    );
  }, [shots]);

  useEffect(() => {
    seenLayouts.current = new Set();
    setLoadedProjectId(null);
    setQueuePaused(false);
    setContextUsage([]);
    setChatSession(IDLE_CHAT_SESSION);
    if (!projectId) {
      replaceShots([]);
      setMessages([
        {
          role: "assistant",
          content:
            "Select or create a project in the header. Then talk to me about the story, shots, or composition, and I will help move the project forward.",
        },
      ]);
      return;
    }
    setBusy(true);
    setError(null);
    setPollError(null);
    Promise.all([
      loadProject(projectId),
      getDirectorChatHistory(projectId).catch(() => []),
      getDirectorChatSession(projectId),
    ])
      .then(([d, savedMessages, session]) => {
        const entries = d.shots.flatMap((shot) => layoutChatEntries(shot).map((entry) => ({ shot, entry })));
        for (const { entry } of entries) {
          seenLayouts.current.add(entry.key);
        }
        setMessages(savedMessages.length ? savedMessages : [
            {
              role: "assistant",
              content:
                `Working on **${d.project.name}**.\n` +
                (d.shots.length
                  ? `${d.shots.length} shot${d.shots.length === 1 ? "" : "s"} planned. Ask about progress, revise an idea, generate reference frames, or write an H3 prompt.`
                  : `The script is about ${(d.project.script_text || "").length} characters long. Send me the story or ask me to plan the shots.`),
              images: entries.map(({ shot, entry }) => ({
                url: entry.url,
                caption: `${shot.title} · ${entry.purpose}`,
                shot_id: shot.id,
              })),
            },
          ]);
        setChatSession(session);
        if (session.active) {
          setLiveRuntime("LLM busy — response is still running");
        }
        setLoadedProjectId(projectId);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  }, [projectId, loadProject, replaceShots]);

  useEffect(() => {
    if (!projectId || !chatActive) return;
    let disposed = false;
    const poll = async () => {
      try {
        const session = await getDirectorChatSession(projectId);
        if (disposed) return;
        if (session.active) {
          setChatSession(session);
          setLiveRuntime("LLM busy — response is still running");
          return;
        }
        setChatSession(IDLE_CHAT_SESSION);
        setLiveStatus([]);
        setLiveRuntime("");
        setLiveThink("");
        setLiveTokens("");
        const [savedMessages] = await Promise.all([
          getDirectorChatHistory(projectId),
          loadProject(projectId),
          refreshProjects(),
        ]);
        if (!disposed) setMessages(savedMessages);
      } catch (cause) {
        if (!disposed) {
          setPollError(
            `Could not refresh Director response status: ${cause instanceof Error ? cause.message : String(cause)}`,
          );
        }
      }
    };
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [chatActive, loadProject, projectId, refreshProjects]);

  useEffect(() => {
    if (!active || !projectId || chatActive) return;
    let disposed = false;
    const timer = window.setInterval(() => {
      getDirectorChatHistory(projectId)
        .then((saved) => {
          if (!disposed) setMessages(saved);
        })
        .catch(() => undefined);
    }, 20000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [active, chatActive, projectId]);

  const needsShotPoll = shots.some(shouldPollShot);

  // Poll while jobs run; when a new layout appears, push it into the chat
  useEffect(() => {
    if (!projectId || !needsShotPoll) return;
    const t = window.setInterval(() => {
      const revisionAtRequest = shotRevision.current;
      getProject(projectId)
        .then((d) => {
          if (revisionAtRequest !== shotRevision.current) return;
          if (shotPollSignature(d.shots) === lastPollSignature.current) {
            setPollError(null);
            return;
          }
          replaceShots(d.shots);
          setPollError(null);
          const fresh = d.shots.flatMap((shot) =>
            layoutChatEntries(shot)
              .filter((entry) => !seenLayouts.current.has(entry.key))
              .map((entry) => ({ shot, entry })),
          );
          if (fresh.length) {
            for (const { entry } of fresh) {
              seenLayouts.current.add(entry.key);
            }
            setMessages((m) => [
              ...m,
              {
                role: "assistant",
                content: `Reference frame${fresh.length === 1 ? " is" : "s are"} ready for review: ${fresh.map(({ shot, entry }) => `${shot.title} (${entry.purpose})`).join(", ")}`,
                images: fresh.map(({ shot, entry }) => ({
                  url: entry.url,
                  caption: `${shot.title} · ${entry.purpose}`,
                  shot_id: shot.id,
                })),
              },
            ]);
          }
        })
        .catch((cause) => {
          setPollError(`Could not refresh Layout status: ${cause instanceof Error ? cause.message : String(cause)}`);
        });
    }, 2500);
    return () => window.clearInterval(t);
  }, [projectId, needsShotPoll, replaceShots]);

  const nearChatBottom = (log: HTMLDivElement) =>
    log.scrollHeight - log.scrollTop - log.clientHeight < 96;

  const scrollChatToBottom = () => {
    const log = chatLogRef.current;
    if (!log) return;
    log.scrollTop = log.scrollHeight;
    setStickToBottom(true);
  };

  useEffect(() => {
    if (!stickToBottom) return;
    const log = chatLogRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, busy, liveStatus, liveRuntime, liveThink, liveTokens, stickToBottom]);

  const send = async (
    text?: string,
    options?: { preserveComposer?: boolean; images?: PendingChatImage[] },
  ): Promise<SendResult> => {
    const preserveComposer = options?.preserveComposer === true;
    const outgoingImages = options?.images ?? (preserveComposer ? [] : [...pendingImages]);
    const typedMessage = (text ?? draft).trim();
    const message = typedMessage || (outgoingImages.length ? "Please analyze the attached image(s)." : "");
    if (!message) return "skipped";
    if (canQueue && projectId && !options?.images) {
      chatQueue.enqueue(projectId, message, outgoingImages);
      if (!preserveComposer) {
        setDraft("");
        setPendingImages([]);
      }
      return "queued";
    }
    if (chatDisabled) return "skipped";
    setStickToBottom(true);
    if (!projectId) {
      setBusy(true);
      setError(null);
      try {
        const name =
          message.length < 40 && !message.includes("\n")
            ? message
            : message.split("\n")[0].slice(0, 40) || "Chat Project";
        const script = message.length >= 40 || message.includes("\n") ? message : "";
        const p = await createAndSelect(name, script);
        setMessages((m) => [
          ...m,
          { role: "user", content: message },
          {
            role: "assistant",
            content: script
              ? `Created **${p.name}** and saved the script. Ask me to plan the shots when you are ready.`
              : `Created **${p.name}**. Send me the story or script to get started.`,
          },
        ]);
        setDraft("");
        await refreshProjects();
        return "sent";
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return "failed";
      } finally {
        setBusy(false);
      }
    }

    const outgoingDraft = draft;
    const optimisticMessageId = `director-local-${Date.now()}-${Math.random()}`;
    if (!preserveComposer) setDraft("");
    const requestMessage = message;
    setContextUsage([]);
    if (!preserveComposer) setPendingImages([]);
    setMessages((m) => [
      ...m,
      {
        id: optimisticMessageId,
        role: "user",
        content: message,
        images: outgoingImages.map((image) => ({
          url: image.previewUrl,
          caption: image.file.name,
        })),
      },
    ]);
    setBusy(true);
    setError(null);
    setLiveStatus([]);
    setLiveRuntime("");
    setLiveThink("");
    setLiveTokens("");
    const controller = new AbortController();
    chatAbortRef.current = controller;
    setChatSession({
      active: true,
      session_id: null,
      started_at: new Date().toISOString(),
    });
    try {
      const handlers = {
        onContextUsage: (usage: ContextUsage) => {
          if (chatAbortRef.current !== controller || controller.signal.aborted || usageProjectRef.current !== projectId) return;
          setContextUsage((calls) => {
            const existing = calls.findIndex((call) => call.call_id === usage.call_id);
            return (existing < 0 ? [...calls, usage] : calls.map((call, index) => index === existing ? usage : call)).slice(-64);
          });
        },
        onStatus: (t: string) => setLiveStatus((s) => [...s.slice(-40), t]),
        onRuntime: (t: string) => setLiveRuntime(t),
        onThink: (t: string) => setLiveThink((prev) => prev + t),
        onToken: (t: string) => setLiveTokens((prev) => prev + t),
        onTool: (t: string) => setLiveStatus((s) => [...s.slice(-40), t]),
      };
      const res = outgoingImages.length
        ? await chatWithDirectorStream(
            projectId,
            requestMessage,
            [],
            handlers,
            outgoingImages.map((image) => image.file),
            controller.signal,
          )
        : await chatWithDirectorStream(
            projectId,
            requestMessage,
            [],
            handlers,
            [],
            controller.signal,
          );
      const images = (res.images || []).filter((img) => img.url);
      for (const img of images) {
        const sid = img.shot_id;
        if (sid) {
          const sh = res.shots.find((s) => s.id === sid);
          if (sh) {
            for (const entry of layoutChatEntries(sh)) {
              if (entry.url === img.url) seenLayouts.current.add(entry.key);
            }
          }
        }
      }
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: res.reply,
          images: images.length ? images : undefined,
          thinking: (res.thinking || "").trim() || undefined,
          steps: res.steps?.length ? res.steps : undefined,
          choices: res.choices?.length ? res.choices : undefined,
        },
      ]);
      replaceShots(res.shots);
      await refreshProjects();
      return "sent";
    } catch (e) {
      if (
        controller.signal.aborted
        || (e instanceof DOMException && e.name === "AbortError")
      ) {
        return "cancelled";
      }
      if (e instanceof DirectorChatError && e.code === "GPU_GENERATION_ACTIVE") {
        if (!preserveComposer) {
          setDraft(outgoingDraft);
          setPendingImages(outgoingImages);
        }
        setMessages((current) => current.filter((message) => message.id !== optimisticMessageId));
        void refreshVramStatus();
        return "failed";
      }
      const err = e instanceof Error ? e.message : String(e);
      setError(err);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: `Something went wrong: ${err}`,
        },
      ]);
      return "failed";
    } finally {
      if (chatAbortRef.current === controller) {
        chatAbortRef.current = null;
      }
      if (usageProjectRef.current === projectId) {
        setContextUsage((calls) => calls.map((call) => call.status === "running"
          ? { ...call, status: controller.signal.aborted ? "cancelled" : "failed" }
          : call));
      }
      setChatSession(IDLE_CHAT_SESSION);
      setBusy(false);
      setLiveStatus([]);
      setLiveRuntime("");
      setLiveThink("");
      setLiveTokens("");
    }
  };

  const cancelChat = async () => {
    if (!projectId || !chatActive || llmBusy) return;
    setLlmBusy(true);
    setError(null);
    // Cancelling means "stop": do not immediately fire the next queued message.
    if (chatQueue.items.length) setQueuePaused(true);
    try {
      chatAbortRef.current?.abort();
      await cancelDirectorChatSession(projectId);
      setChatSession(IDLE_CHAT_SESSION);
      setMessages(await getDirectorChatHistory(projectId));
      setLiveStatus([]);
      setLiveRuntime("");
      setLiveThink("");
      setLiveTokens("");
      setBusy(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLlmBusy(false);
    }
  };

  useEffect(() => {
    if (
      !requestedMessage
      || requestedMessage.projectId !== projectId
      || loadedProjectId !== projectId
      || chatDisabled
      || handledRequestId.current === requestedMessage.id
    ) return;
    handledRequestId.current = requestedMessage.id;
    void send(requestedMessage.message);
  }, [requestedMessage, projectId, loadedProjectId, chatDisabled]); // eslint-disable-line react-hooks/exhaustive-deps

  // Send queued messages one at a time once the Director is idle. The refs guard
  // against effect re-runs and a same-render requested send; a failed send goes
  // back to the head and pauses the queue.
  useEffect(() => {
    if (
      !projectId
      || loadedProjectId !== projectId
      || chatDisabled
      || queuePaused
      || dispatchingRef.current
      || chatAbortRef.current
    ) return;
    const next: QueuedChatMessage | undefined = chatQueue.items[0];
    if (!next) return;
    dispatchingRef.current = true;
    const targetId = projectId;
    chatQueue.take(targetId, next.id);
    void send(next.text, { preserveComposer: true, images: next.images })
      .then((result) => {
        if (result === "failed" || result === "skipped") {
          chatQueue.restoreHead(targetId, next);
          setQueuePaused(true);
        }
      })
      .finally(() => {
        dispatchingRef.current = false;
        setDispatchTick((tick) => tick + 1);
      });
  }, [chatQueue.items, projectId, loadedProjectId, chatDisabled, queuePaused, dispatchTick]); // eslint-disable-line react-hooks/exhaustive-deps

  const updateShot = (updated: Shot) => {
    shotRevision.current += 1;
    setShots((current) => current.map((shot) => shot.id === updated.id ? updated : shot));
  };

  const scriptLocked = Boolean(project?.script_locked);
  const chips = [
    { label: "Project status", text: "status" },
    ...(scriptLocked
      ? [
          { label: "Plan shots", text: "plan" },
          {
            label: "Discuss Layouts",
            text: "I want to discuss whether any shots would benefit from optional Layout studies. Ask what visual states I want before proposing sources. Do not queue generation yet.",
          },
        ]
      : []),
  ];
  const promptRetryMessage =
    "Retry the previous failed H3 prompt once. Preserve the current storyboard, Picture references, dialogue, and shot structure. Correct only the reported prompt validation error. Do not generate a Layout or change the story.";
  const isPromptGenerationFailure = (content: string) => {
    const normalized = content.toLowerCase();
    return normalized.includes("prompt generation did not complete after bounded internal repair")
      || normalized.includes("prompt_generation_failed");
  };
  const selectedShotIndex = Math.max(0, shots.findIndex((shot) => shot.id === selectedShotId));
  const selectedShot = shots[selectedShotIndex] ?? null;
  const shotNumber = String(selectedShotIndex + 1).padStart(2, "0");
  const nextChip = selectedShot
    ? shotWorkflowStatus(selectedShot).key === "ready-for-h3"
      ? {
          label: `Run H3 · ${shotNumber}`,
          text: `Queue H3 for shot ${selectedShotIndex + 1}`,
        }
      : {
          label: `Write H3 · ${shotNumber}`,
          text: `Write the H3 prompt for shot ${selectedShotIndex + 1}`,
        }
    : scriptLocked
      ? { label: "Plan shots", text: "plan" }
      : null;
  const chipRow = mobile
    ? [{ label: "Project status", text: "status" }, ...(nextChip ? [nextChip] : [])]
    : [
        ...chips,
        ...(selectedShot
          ? [{
              label: `Write H3 prompt · Shot ${shotNumber}`,
              text: `Write the H3 prompt for shot ${selectedShotIndex + 1}`,
            }]
          : []),
      ];

  const chatPanel = (
    <section className="panel director-chat-panel">
        <div className="director-chat-header workspace-panel-header">
          <div className="director-chat-header-row">
            <div className="director-identity">
              <img
                className="director-agent-mascot"
                src="/director-agent-shot-board.png"
                alt="Director Agent holding a shot board"
              />
              <div>
                <h2>Director</h2>
                {!projectId ? (
                  <p className="project-scope-hint">
                    Select a project, or create one with your first message
                  </p>
                ) : null}
              </div>
            </div>
            <div className="director-runtime-controls">
              <label className="director-model-picker inline-model-picker">
                <span className="muted tiny">Soul</span>
                <select
                  aria-label="Director soul"
                  value={project?.soul_id || souls[0]?.id || "studio"}
                  disabled={chatDisabled || soulBusy || souls.length === 0}
                  onChange={(event) => void onChangeSoul(event.target.value)}
                  title="Directing persona for this project"
                >
                  {souls.map((soul) => (
                    <option key={soul.id} value={soul.id}>{soul.name}</option>
                  ))}
                </select>
              </label>
              <label className="director-model-picker inline-model-picker">
                <span className="muted tiny">LLM</span>
                <select
                  aria-label="Director LLM"
                  value={llmOptions.length ? llmModel : ""}
                  disabled={chatDisabled || llmBusy || llmOptions.length === 0}
                  onChange={(e) => void onChangeLlm(e.target.value)}
                  title={`${llmProvider} model used for Director chat and shot planning`}
                >
                  {llmOptions.length === 0 ? (
                    <option value="">{llmReachable ? "No models available" : `${llmProvider} unavailable`}</option>
                  ) : (
                    <>
                      {llmModel && !llmOptions.includes(llmModel) ? (
                        <option value={llmModel} disabled>{llmModel} (not available)</option>
                      ) : null}
                      {llmOptions.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </>
                  )}
                </select>
              </label>
              <ContextUsagePanel calls={contextUsage} compact={mobile}>
                {projectId ? <ContextCompaction key={projectId} projectId={projectId}
                  disabled={busy || generationLocked || chatActive || llmBusy || !llmModel}
                  onBusyChange={setCompactingContext} /> : null}
              </ContextUsagePanel>
            </div>
          </div>
        </div>
        {project ? (
          <>
            {!(project.script_text || "").trim() && !project.script_locked ? (
              <ScreenplayInterviewPanel
                project={project}
                disabled={busy || generationLocked || chatActive}
                onDrafted={() => { void refreshProjects(); }}
              />
            ) : (
              <ScriptDraftPanel
                project={project}
                disabled={busy || generationLocked || chatActive}
                onUpdated={() => { void refreshProjects(); }}
              />
            )}
          </>
        ) : null}
        {projectId ? (
          <MemoryNotes projectId={projectId} disabled={busy || generationLocked || chatActive}>
            <MemoryPatrolStatus projectId={projectId} />
          </MemoryNotes>
        ) : null}

        {mobile && !chatOnly ? (
          <MobileShotDrawer
            shots={shots}
            selectedId={selectedShotId}
            onSelectShot={setSelectedShotId}
            onSend={(message) => void send(message)}
            sendDisabled={chatDisabled}
            onShotUpdated={updateShot}
            onOpenImage={setLightbox}
          />
        ) : null}

        <div className="director-chat-thread">
        {error ? <div className="banner error">{error}</div> : null}
        {pollError ? <div className="banner error" role="alert" aria-live="polite">{pollError}</div> : null}
        {vramPollError ? <div className="banner error" role="alert" aria-live="polite">{vramPollError}</div> : null}

        <div
          className={`director-work-banner${chatActive || busy ? " director-work-banner-busy" : ""}`}
          role="status"
          aria-live="polite"
        >
          {chatActive || busy
            ? `Working${liveStatus.length ? ` · ${liveStatus[liveStatus.length - 1]}` : liveRuntime ? ` · ${liveRuntime}` : " · Director turn in progress"}`
            : "Idle · no Director turn running. A plan in chat is not saved work until a tool succeeds."}
        </div>

        {vramStatus && generationStatusText(vramStatus, clockNow) ? (
          <div className="director-generation-status" role="status" aria-live="polite">
            <span className="director-generation-dot" aria-hidden="true" />
            <span>{generationStatusText(vramStatus, clockNow)}</span>
          </div>
        ) : null}

        <div className="chat-log-wrap">
        <div
          className="chat-log"
          ref={chatLogRef}
          onScroll={(event) => {
            setStickToBottom(nearChatBottom(event.currentTarget));
          }}
        >
          {messages.map((m, i) => {
            const images = visibleChatImages(m.images, shots);
            const canRetryPrompt = m.role === "assistant"
              && i === messages.length - 1
              && isPromptGenerationFailure(m.content);
            return (
              <div
                key={m.id || i}
                className={`chat-bubble ${m.role === "user" ? "user" : "assistant"}`}
              >
              <div className="chat-role">{m.role === "user" ? "You" : "Director"}</div>
              {m.steps?.length ? (
                <details className="chat-trace" open={m.steps.some((step) => /failed|blocked/i.test(step))}>
                  <summary>Process ({m.steps.length})</summary>
                  <ol className="chat-steps">
                    {m.steps.map((s, j) => (
                      <li key={j}>{s}</li>
                    ))}
                  </ol>
                </details>
              ) : null}
              {m.thinking ? (
                <details className="chat-think" open={false}>
                  <summary>Reasoning</summary>
                  <pre className="chat-think-body">{m.thinking}</pre>
                </details>
              ) : null}
              <div className="chat-content">{m.content}</div>
              {(() => {
                const interactive = i === messages.length - 1 && m.role === "assistant";
                const questions = m.choices?.length
                  ? m.choices
                  : interactive
                    ? parseChoiceQuestionsFromText(m.content)
                    : [];
                if (!interactive || !questions.length) return null;
                return (
                  <ChoiceChecklist
                    questions={questions}
                    disabled={busy || chatActive}
                    onSubmit={(text) => void send(text)}
                  />
                );
              })()}
              {canRetryPrompt ? (
                <div className="chat-message-actions">
                  <button
                    type="button"
                    className="prompt-retry-button"
                    disabled={chatDisabled}
                    onClick={() => void send(promptRetryMessage, { preserveComposer: true })}
                  >
                    Retry prompt
                  </button>
                </div>
              ) : null}
              {images.length ? (
                <div className="chat-images">
                  {images.map((img, j) => (
                    <ChatImageCard
                      key={j}
                      url={img.url}
                      caption={img.caption}
                      onOpen={setLightbox}
                    />
                  ))}
                </div>
              ) : null}
              </div>
            );
          })}
          {busy || chatActive ? (
            <div className="chat-bubble assistant live">
              <div className="chat-role">Director · Working</div>
              {liveStatus.length ? (
                <div className="chat-trace open">
                  <div className="chat-trace-label">Process</div>
                  <ol className="chat-steps">
                    {liveStatus.map((s, j) => (
                      <li key={j}>{s}</li>
                    ))}
                  </ol>
                </div>
              ) : !liveRuntime ? (
                <div className="chat-content muted">Connecting…</div>
              ) : null}
              {liveRuntime ? (
                <div className="chat-runtime" aria-live="polite">
                  <div className="chat-trace-label">Runtime</div>
                  <div>{liveRuntime}</div>
                </div>
              ) : null}
              {liveThink ? (
                <div className="chat-think open">
                  <div className="chat-trace-label">Reasoning</div>
                  <pre className="chat-think-body">{liveThink}</pre>
                </div>
              ) : null}
              {liveTokens ? (
                <div className="chat-content draft-tokens">{liveTokens}</div>
              ) : null}
            </div>
          ) : null}
        </div>
        {!stickToBottom ? (
          <button
            type="button"
            className="chat-jump-bottom"
            aria-label="Jump to latest"
            title="Jump to latest"
            onClick={scrollChatToBottom}
          >
            <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
              <path
                d="M4.2 7.2a1 1 0 0 1 1.4 0L10 11.6l4.4-4.4a1 1 0 1 1 1.4 1.4l-5.1 5.1a1 1 0 0 1-1.4 0L4.2 8.6a1 1 0 0 1 0-1.4z"
                fill="currentColor"
              />
            </svg>
          </button>
        ) : null}
        </div>

        {!chatOnly ? <div className="chat-chips">
          {chipRow.map((c) => (
            <button
              key={c.label}
              type="button"
              className="mode-chip"
              disabled={composerDisabled}
              onClick={() => void send(c.text)}
            >
              {c.label}
            </button>
          ))}
        </div> : null}

        {pendingImages.length ? (
          <div className="chat-attachment-tray" aria-label="Attached images">
            {pendingImages.map((image, index) => (
              <div className="chat-attachment" key={`${image.file.name}-${index}`}>
                <img src={image.previewUrl} alt={image.file.name} />
                <span title={image.file.name}>{image.file.name}</span>
                <button
                  type="button"
                  aria-label={`Remove ${image.file.name}`}
                  disabled={chatDisabled}
                  onClick={() => removeChatImage(index)}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        ) : null}

        {projectId && chatQueue.items.length ? (
          <div className="chat-queue" aria-label="Queued messages">
            <div className="chat-queue-header">
              <span>
                Queued ({chatQueue.items.length})
                {queuePaused ? <span className="chat-queue-paused"> · paused</span> : null}
              </span>
              <div className="chat-queue-actions">
                {queuePaused ? (
                  <button type="button" className="btn ghost sm" onClick={() => setQueuePaused(false)}>
                    Resume
                  </button>
                ) : null}
                <button type="button" className="btn ghost sm" onClick={() => chatQueue.clear(projectId)}>
                  Clear
                </button>
              </div>
            </div>
            <ol className="chat-queue-list">
              {chatQueue.items.map((item) => (
                <li
                  key={item.id}
                  className="chat-queue-item"
                  title={item.images.length ? `${item.text}\n(Images are kept in memory only and are lost on refresh.)` : item.text}
                >
                  <span className="chat-queue-text">{item.text}</span>
                  {item.images.length ? (
                    <span className="chat-queue-images">
                      {item.images.length} image{item.images.length === 1 ? "" : "s"}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    aria-label={`Remove queued message: ${item.text.slice(0, 40)}`}
                    onClick={() => chatQueue.remove(projectId, item.id)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        <div className="chat-composer">
          <label
            className={`chat-upload-btn${!projectId || chatDisabled || pendingImages.length >= MAX_CHAT_IMAGES ? " disabled" : ""}`}
            title={projectId ? "Add up to 4 images" : "Select a project before adding images"}
          >
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              aria-label="Add images"
              disabled={!projectId || chatDisabled || pendingImages.length >= MAX_CHAT_IMAGES}
              onChange={(event) => {
                addChatImages(event.target.files);
                event.target.value = "";
              }}
            />
            <span aria-hidden="true">+</span>
          </label>
          <textarea
            rows={mobile ? 2 : 3}
            value={draft}
            disabled={composerDisabled}
            aria-label="Message to Director"
            placeholder={
              projectId
                ? canQueue
                  ? "Talk to the Director… the Director is working, so this will be queued."
                  : "Talk to the Director about the story, a weak shot, or what you want to change…"
                : "Enter a project name, or paste a script to create a project…"
            }
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          {canQueue ? (
            <button
              type="button"
              className="btn secondary"
              disabled={!draft.trim() && pendingImages.length === 0}
              onClick={() => void send()}
            >
              Queue
            </button>
          ) : null}
          {chatActive ? (
            <button
              type="button"
              className="btn danger"
              disabled={llmBusy}
              onClick={() => void cancelChat()}
            >
              Cancel
            </button>
          ) : canQueue ? null : (
            <button
              type="button"
              className="btn primary"
              disabled={chatDisabled || (!draft.trim() && pendingImages.length === 0)}
              onClick={() => void send()}
            >
              Send
            </button>
          )}
        </div>
        </div>
    </section>
  );
  const shotPanel = (
    <ShotWorkspace
      shots={shots}
      busy={busy}
      onSend={(message) => void send(message)}
      onSelectShot={(shot) => setSelectedShotId(shot.id)}
      onShotUpdated={updateShot}
      onOpenImage={setLightbox}
    />
  );

  return (
    <main className={`workspace director-chat-layout${!chatOnly && !mobile ? " director-fill-viewport" : ""}${chatOnly ? " chat-only" : ""}${mobile ? " mobile-director-layout" : ""}`}>
      {chatOnly || mobile ? chatPanel : (
        <ResizableWorkspace
          className="director-resizable-workspace"
          storageKey="ds.directorChatWidth"
          separatorLabel="Resize Director chat and Shots"
          primary={chatPanel}
          secondary={shotPanel}
        />
      )}

      {lightbox ? (
        <div
          className="lightbox-overlay"
          role="dialog"
          onClick={() => setLightbox(null)}
          onKeyDown={(e) => e.key === "Escape" && setLightbox(null)}
        >
          <img src={lightbox} alt="full preview" className="lightbox-img" />
        </div>
      ) : null}
    </main>
  );
}
