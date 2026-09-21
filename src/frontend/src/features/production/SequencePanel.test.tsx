// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SequencePanel } from "./SequencePanel";
import { assembleSequence, getSequence } from "./sequenceApi";
import type { SequenceReport } from "./sequenceApi";

vi.mock("./sequenceApi", () => ({
  getSequence: vi.fn(),
  assembleSequence: vi.fn(),
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
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getSequence).mockResolvedValue(report());
  });

  it("shows runtime, clip readiness, and export links", async () => {
    render(<SequencePanel projectId="prj_test" />);
    expect(await screen.findByText(/2 shots · 1 scenes · 0:12 planned · 1 clips ready/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Assemble rough cut" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "SRT" }).getAttribute("href")).toBe(
      "/api/projects/prj_test/sequence/export/srt",
    );
    expect(screen.getByText("Shot 02 has no succeeded H3 clip.")).toBeTruthy();
  });

  it("selects a shot from the timeline and from a continuity note", async () => {
    const onSelectShot = vi.fn();
    render(<SequencePanel projectId="prj_test" onSelectShot={onSelectShot} />);
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
    fireEvent.click(await screen.findByRole("button", { name: "Assemble rough cut" }));
    await waitFor(() => expect(assembleSequence).toHaveBeenCalledWith("prj_test"));
    expect(await screen.findByText(/skipped 1 shot/)).toBeTruthy();
    expect(screen.getByLabelText("Rough cut")).toBeTruthy();
  });
});
