// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SequencePanel } from "./SequencePanel";
import {
  assembleSequence,
  cancelProductionQueue,
  getProductionQueue,
  getSequence,
  startProductionQueue,
} from "./sequenceApi";
import type { SequenceReport } from "./sequenceApi";

vi.mock("./sequenceApi", () => ({
  getSequence: vi.fn(),
  assembleSequence: vi.fn(),
  getProductionQueue: vi.fn(async () => ({
    project_id: "prj_test",
    mode: "next",
    status: "idle",
    current_shot_id: null,
    current_job_id: null,
    pending_shot_ids: [],
    completed_shot_ids: [],
    chain_tail_frames: true,
    error: null,
    updated_at: "",
  })),
  startProductionQueue: vi.fn(),
  cancelProductionQueue: vi.fn(),
  sequenceExportUrl: (id: string, kind: string) =>
    `/api/projects/${id}/sequence/export/${kind}`,
}));

function report(overrides: Partial<SequenceReport> = {}): SequenceReport {
  return {
    project_id: "prj_test",
    project_name: "Test",
    shot_count: 2,
    scene_count: 1,
    planned_duration_s: 12,
    assembled_duration_s: 6,
    clips_ready: 1,
    clips_missing: 1,
    runtime: "0:12",
    shots: [
      {
        shot_id: "sht_a",
        index: 1,
        scene_id: "sc01",
        title: "Entry",
        script_beat: "Kai enters.",
        shot_type: "wide",
        camera_angle: "eye level",
        camera_motion: "locked-off",
        composition: "doorway",
        duration_s: 6,
        status: "succeeded",
        dialogue: ["Kai: Hello."],
        actor_ids: ["act_kai"],
        scene_asset_ids: ["scn_hall"],
        costume_ids: [],
        prop_ids: [],
        voice_speakers: ["Kai"],
        has_layout: true,
        has_tail_from_previous: false,
        clip_status: "ready",
        clip_job_id: "job_1",
        clip_url: "/clip-a.mp4",
        clip_filename: "video.mp4",
      },
      {
        shot_id: "sht_b",
        index: 2,
        scene_id: "sc01",
        title: "Hold",
        script_beat: "Kai waits.",
        shot_type: "medium",
        camera_angle: "eye level",
        camera_motion: "locked-off",
        composition: "desk",
        duration_s: 6,
        status: "draft",
        dialogue: [],
        actor_ids: ["act_kai"],
        scene_asset_ids: ["scn_hall"],
        costume_ids: [],
        prop_ids: [],
        voice_speakers: [],
        has_layout: false,
        has_tail_from_previous: false,
        clip_status: "missing",
        clip_job_id: null,
        clip_url: null,
        clip_filename: null,
      },
    ],
    issues: [
      {
        severity: "warning",
        code: "missing_clip",
        shot_id: "sht_b",
        related_shot_id: null,
        message: "Shot 02 has no succeeded H3 clip.",
      },
    ],
    last_assembly: null,
    ...overrides,
  };
}

describe("SequencePanel", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getSequence).mockResolvedValue(report());
    vi.mocked(getProductionQueue).mockResolvedValue({
      project_id: "prj_test",
      mode: "next",
      status: "idle",
      current_shot_id: null,
      current_job_id: null,
      pending_shot_ids: [],
      completed_shot_ids: [],
      chain_tail_frames: true,
      error: null,
      updated_at: "",
    });
  });

  it("shows runtime, clip readiness, and export links", async () => {
    render(<SequencePanel projectId="prj_test" />);
    expect(await screen.findByText(/2 shots · 1 scenes · 0:12 planned · 1 clips ready/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Cut tools"));
    expect(screen.getByRole("button", { name: "Assemble rough cut" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "SRT" }).getAttribute("href")).toBe(
      "/api/projects/prj_test/sequence/export/srt",
    );
    expect(screen.getByText("Shot 02 has no succeeded H3 clip.")).toBeTruthy();
  });

  it("selects a shot from the timeline and from a continuity note", async () => {
    const onSelectShot = vi.fn();
    render(<SequencePanel projectId="prj_test" onSelectShot={onSelectShot} />);
    fireEvent.click(await screen.findByLabelText("Cut tools"));
    fireEvent.click(await screen.findByRole("button", { name: /01/ }));
    expect(onSelectShot).toHaveBeenCalledWith("sht_a");
    fireEvent.click(screen.getByText("Shot 02 has no succeeded H3 clip."));
    expect(onSelectShot).toHaveBeenCalledWith("sht_b");
  });

  it("assembles a rough cut and then shows the result", async () => {
    vi.mocked(assembleSequence).mockResolvedValue({
      filename: "rough_cut.mp4",
      url: "/api/files/projects/prj_test/sequence/rough_cut.mp4",
      duration_s: 6,
      shot_ids: ["sht_a"],
      missing_shot_ids: ["sht_b"],
      clip_job_ids: ["job_1"],
      created_at: "2026-09-20T00:00:00Z",
    });
    vi.mocked(getSequence)
      .mockResolvedValueOnce(report())
      .mockResolvedValueOnce(
        report({
          last_assembly: {
            filename: "rough_cut.mp4",
            url: "/api/files/projects/prj_test/sequence/rough_cut.mp4",
            duration_s: 6,
            shot_ids: ["sht_a"],
            missing_shot_ids: ["sht_b"],
            clip_job_ids: ["job_1"],
            created_at: "2026-09-20T00:00:00Z",
          },
        }),
      );

    render(<SequencePanel projectId="prj_test" />);
    fireEvent.click(await screen.findByLabelText("Cut tools"));
    fireEvent.click(await screen.findByRole("button", { name: "Assemble rough cut" }));
    await waitFor(() => expect(assembleSequence).toHaveBeenCalledWith("prj_test"));
    expect(await screen.findByText(/skipped 1 shot/)).toBeTruthy();
    expect(screen.getByLabelText("Rough cut")).toBeTruthy();
  });

  it("rebuilds a stale rough cut when new clips appear", async () => {
    vi.mocked(assembleSequence).mockResolvedValue({
      filename: "rough_cut.mp4",
      url: "/api/files/projects/prj_test/sequence/rough_cut.mp4",
      duration_s: 12,
      shot_ids: ["sht_a", "sht_b"],
      missing_shot_ids: [],
      clip_job_ids: ["job_1", "job_2"],
      created_at: "2026-09-22T18:00:00Z",
    });
    vi.mocked(getSequence)
      .mockResolvedValueOnce(
        report({
          clips_ready: 2,
          clips_missing: 0,
          last_assembly: {
            filename: "rough_cut.mp4",
            url: "/api/files/projects/prj_test/sequence/rough_cut.mp4",
            duration_s: 6,
            shot_ids: ["sht_a"],
            missing_shot_ids: ["sht_b"],
            clip_job_ids: ["job_old"],
            created_at: "2026-09-22T16:00:00Z",
          },
          shots: report().shots.map((shot, index) =>
            index === 1
              ? { ...shot, clip_status: "ready", clip_job_id: "job_2", status: "succeeded" }
              : shot,
          ),
        }),
      )
      .mockResolvedValue(
        report({
          clips_ready: 2,
          last_assembly: {
            filename: "rough_cut.mp4",
            url: "/api/files/projects/prj_test/sequence/rough_cut.mp4",
            duration_s: 12,
            shot_ids: ["sht_a", "sht_b"],
            missing_shot_ids: [],
            clip_job_ids: ["job_1", "job_2"],
            created_at: "2026-09-22T18:00:00Z",
          },
        }),
      );

    render(<SequencePanel projectId="prj_test" />);
    await waitFor(() => expect(assembleSequence).toHaveBeenCalledWith("prj_test"));
  });

  it("starts the next unfinished shot from the production queue", async () => {
    vi.mocked(startProductionQueue).mockResolvedValue({
      project_id: "prj_test",
      mode: "next",
      status: "running",
      current_shot_id: "sht_b",
      current_job_id: "job_q",
      pending_shot_ids: [],
      completed_shot_ids: ["sht_a"],
      chain_tail_frames: true,
      error: null,
      updated_at: "2026-09-22T00:00:00Z",
    });
    render(<SequencePanel projectId="prj_test" />);
    fireEvent.click(await screen.findByLabelText("Cut tools"));
    fireEvent.click(await screen.findByRole("button", { name: "Run next" }));
    await waitFor(() =>
      expect(startProductionQueue).toHaveBeenCalledWith("prj_test", {
        mode: "next",
        from_shot_id: "sht_b",
        chain_tail_frames: true,
      }),
    );
    expect(await screen.findByRole("button", { name: "Stop queue" })).toBeTruthy();
    expect(screen.getByText(/Queue next · current sht_b/)).toBeTruthy();
  });

  it("starts remaining unfinished shots and can stop the queue", async () => {
    vi.mocked(startProductionQueue).mockResolvedValue({
      project_id: "prj_test",
      mode: "remaining",
      status: "running",
      current_shot_id: "sht_b",
      current_job_id: "job_q",
      pending_shot_ids: ["sht_c"],
      completed_shot_ids: [],
      chain_tail_frames: true,
      error: null,
      updated_at: "2026-09-22T00:00:00Z",
    });
    vi.mocked(cancelProductionQueue).mockResolvedValue({
      project_id: "prj_test",
      mode: "remaining",
      status: "idle",
      current_shot_id: null,
      current_job_id: null,
      pending_shot_ids: [],
      completed_shot_ids: [],
      chain_tail_frames: true,
      error: null,
      updated_at: "2026-09-22T00:00:01Z",
    });
    render(<SequencePanel projectId="prj_test" />);
    fireEvent.click(await screen.findByLabelText("Cut tools"));
    fireEvent.click(await screen.findByRole("button", { name: "Run remaining" }));
    await waitFor(() =>
      expect(startProductionQueue).toHaveBeenCalledWith("prj_test", {
        mode: "remaining",
        from_shot_id: "sht_b",
        chain_tail_frames: true,
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Stop queue" }));
    await waitFor(() => expect(cancelProductionQueue).toHaveBeenCalledWith("prj_test"));
    expect(screen.queryByRole("button", { name: "Stop queue" })).toBeNull();
  });

  it("shows Stop queue while a polled production queue is running", async () => {
    vi.mocked(getProductionQueue).mockResolvedValue({
      project_id: "prj_test",
      mode: "next",
      status: "running",
      current_shot_id: "sht_b",
      current_job_id: "job_q",
      pending_shot_ids: [],
      completed_shot_ids: ["sht_a"],
      chain_tail_frames: true,
      error: null,
      updated_at: "2026-09-22T00:00:00Z",
    });
    render(<SequencePanel projectId="prj_test" />);
    expect(await screen.findByRole("button", { name: "Stop queue" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run next" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Run remaining" }).hasAttribute("disabled")).toBe(true);
    expect(
      (screen.getByRole("checkbox", { name: /Chain tail frame into next shot/ }) as HTMLInputElement)
        .disabled,
    ).toBe(true);
  });

  it("sends chain_tail_frames false when the tail-frame toggle is off", async () => {
    vi.mocked(startProductionQueue).mockResolvedValue({
      project_id: "prj_test",
      mode: "next",
      status: "running",
      current_shot_id: "sht_b",
      current_job_id: "job_q",
      pending_shot_ids: [],
      completed_shot_ids: ["sht_a"],
      chain_tail_frames: false,
      error: null,
      updated_at: "2026-09-22T00:00:00Z",
    });
    render(<SequencePanel projectId="prj_test" />);
    fireEvent.click(await screen.findByLabelText("Cut tools"));
    const toggle = await screen.findByRole("checkbox", {
      name: /Chain tail frame into next shot/,
    });
    expect((toggle as HTMLInputElement).checked).toBe(true);
    fireEvent.click(toggle);
    expect((toggle as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Run next" }));
    await waitFor(() =>
      expect(startProductionQueue).toHaveBeenCalledWith("prj_test", {
        mode: "next",
        from_shot_id: "sht_b",
        chain_tail_frames: false,
      }),
    );
  });

  it("does not poll getSequence while idle", async () => {
    vi.useFakeTimers();
    render(<SequencePanel projectId="prj_test" />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText(/2 shots · 1 scenes · 0:12 planned · 1 clips ready/)).toBeTruthy();
    const initial = vi.mocked(getSequence).mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(9000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getSequence).toHaveBeenCalledTimes(initial);
  });

  it("does not fetch sequence while Production is hidden", async () => {
    render(<SequencePanel projectId="prj_test" active={false} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getSequence).not.toHaveBeenCalled();
    expect(getProductionQueue).not.toHaveBeenCalled();
  });

  it("keeps the last sequence report when Production is hidden", async () => {
    const { rerender } = render(<SequencePanel projectId="prj_test" active />);
    expect(await screen.findByText(/2 shots · 1 scenes · 0:12 planned · 1 clips ready/)).toBeTruthy();
    rerender(<SequencePanel projectId="prj_test" active={false} />);
    expect(screen.getByText(/2 shots · 1 scenes · 0:12 planned · 1 clips ready/)).toBeTruthy();
  });

  it("keeps the sequence report when a later live refresh fails", async () => {
    vi.mocked(getSequence)
      .mockResolvedValueOnce(report())
      .mockRejectedValue(new Error("sequence unavailable"));
    vi.useFakeTimers();
    render(<SequencePanel projectId="prj_test" live />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText(/2 shots · 1 scenes · 0:12 planned · 1 clips ready/)).toBeTruthy();
    await act(async () => {
      vi.advanceTimersByTime(3100);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText(/2 shots · 1 scenes · 0:12 planned · 1 clips ready/)).toBeTruthy();
    expect(screen.getByText("sequence unavailable")).toBeTruthy();
  });

  it("polls getSequence while live", async () => {
    vi.useFakeTimers();
    render(<SequencePanel projectId="prj_test" live />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText(/2 shots · 1 scenes · 0:12 planned · 1 clips ready/)).toBeTruthy();
    const initial = vi.mocked(getSequence).mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(3100);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(vi.mocked(getSequence).mock.calls.length).toBeGreaterThan(initial);
  });
});
