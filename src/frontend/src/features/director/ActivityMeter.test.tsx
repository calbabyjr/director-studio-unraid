// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ActivityMeter } from "./ActivityMeter";
import { cancelDirectorChatSession, cancelDirectorJob, getDirectorVramStatus } from "./api";

vi.mock("./api", () => ({
  getDirectorVramStatus: vi.fn(),
  cancelDirectorJob: vi.fn(),
  cancelDirectorChatSession: vi.fn(),
}));

describe("ActivityMeter", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(cancelDirectorJob).mockResolvedValue(undefined);
    vi.mocked(cancelDirectorChatSession).mockResolvedValue({
      active: false,
      session_id: null,
      started_at: null,
    });
  });

  it("cancels the current Comfy job from the live meter", async () => {
    vi.mocked(getDirectorVramStatus).mockResolvedValue({
      chat_locked: true,
      generation_count: 1,
      generation_jobs: [{
        job_id: "job_h3",
        pipeline_id: "h3_ref2va",
        kind: "video",
        status: "running",
        phase: "generating",
        queued_at: "2026-08-31T10:00:00Z",
      }],
      cancel_job_id: "job_h3",
    });

    render(<ActivityMeter />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(cancelDirectorJob).toHaveBeenCalledWith("job_h3");
    });
    expect(cancelDirectorChatSession).not.toHaveBeenCalled();
  });

  it("cancels an active Director chat turn from the live meter", async () => {
    vi.mocked(getDirectorVramStatus).mockResolvedValue({
      chat_locked: false,
      generation_count: 0,
      generation_jobs: [],
      director_working: true,
      director_chats: [{
        project_id: "prj_chat",
        session_id: "chat_1",
        started_at: "2026-08-31T10:00:00Z",
      }],
    });

    render(<ActivityMeter />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(cancelDirectorChatSession).toHaveBeenCalledWith("prj_chat");
    });
    expect(cancelDirectorJob).not.toHaveBeenCalled();
  });
});
