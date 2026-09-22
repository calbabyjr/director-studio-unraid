// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssetDetailDialog } from "./AssetDetailDialog";
import {
  addActorVoiceSample,
  addLibraryAssetFile,
  listActorTakes,
  pinActorTake,
  updateActorSheet,
  type LibraryAsset,
} from "./api";

vi.mock("./api", () => ({
  addLibraryAssetFile: vi.fn(),
  addActorVoiceSample: vi.fn(),
  listActorTakes: vi.fn(async () => ({ items: [] })),
  pinActorTake: vi.fn(),
  updateActorSheet: vi.fn(),
  getActorJob: vi.fn(async () => ({ id: "job_sheet", status: "queued", error: null })),
  getLibraryAsset: vi.fn(),
}));

const actor: LibraryAsset = {
  id: "act_jenny",
  kind: "actors",
  name: "Jenny",
  notes: "Lead",
  pipeline_id: "external",
  job_id: "",
  seed: null,
  created_at: "2026-01-01T00:00:00Z",
  files: { master: "master.png" },
  meta: {},
  urls: { master: "/api/files/library/actors/act_jenny/master.png" },
  project_id: "prj_test",
};

describe("AssetDetailDialog actor voice samples", () => {
  afterEach(cleanup);

  it("uploads a voice sample onto the actor", async () => {
    vi.mocked(addActorVoiceSample).mockResolvedValue({
      ...actor,
      files: { master: "master.png", voice: "voice.wav" },
      urls: {
        master: "/api/files/library/actors/act_jenny/master.png",
        voice: "/api/files/library/actors/act_jenny/voice.wav",
      },
      meta: { linked_voice_ids: ["voi_jenny"] },
    });
    const onUpdated = vi.fn();
    render(<AssetDetailDialog asset={actor} onClose={() => undefined} onUpdated={onUpdated} />);

    expect(await screen.findByLabelText("Actor takes")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add voice sample" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Voice sample file"), {
      target: { files: [new File(["audio"], "jenny.wav", { type: "audio/wav" })] },
    });

    await waitFor(() => {
      expect(addActorVoiceSample).toHaveBeenCalledOnce();
    });
    const [assetId, file] = vi.mocked(addActorVoiceSample).mock.calls[0];
    expect(assetId).toBe("act_jenny");
    expect(file).toBeInstanceOf(File);
    expect(file.name).toBe("jenny.wav");
    expect(onUpdated).toHaveBeenCalled();
  });

  it("plays an attached actor voice sample", async () => {
    const withVoice: LibraryAsset = {
      ...actor,
      files: { master: "master.png", voice: "voice.wav" },
      urls: {
        master: "/api/files/library/actors/act_jenny/master.png",
        voice: "/api/files/library/actors/act_jenny/voice.wav",
      },
    };
    const { container } = render(
      <AssetDetailDialog asset={withVoice} onClose={() => undefined} />,
    );
    expect(await screen.findByLabelText("Actor takes")).toBeTruthy();
    expect(screen.getByText("Voice sample")).toBeTruthy();
    const player = container.querySelector("audio");
    expect(player?.getAttribute("src")).toBe(
      "/api/files/library/actors/act_jenny/voice.wav",
    );
  });

  it("queues an asset-sheet update from attached stills", async () => {
    vi.mocked(updateActorSheet).mockResolvedValue({
      id: "job_sheet",
      status: "queued",
      error: null,
    });
    render(<AssetDetailDialog asset={actor} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Update asset sheet" }));
    await waitFor(() => expect(updateActorSheet).toHaveBeenCalledWith("act_jenny"));
    expect(screen.getByText(/Sheet job queued/)).toBeTruthy();
  });

  it("does not offer voice samples on a Voice asset", () => {
    render(
      <AssetDetailDialog
        asset={{
          ...actor,
          id: "voi_mia",
          kind: "voices",
          name: "Mia",
          files: { reference: "reference.wav" },
          urls: { reference: "/api/files/library/voices/voi_mia/reference.wav" },
        }}
        onClose={() => undefined}
      />,
    );
    expect(screen.queryByRole("button", { name: "Add voice sample" })).toBeNull();
    expect(addLibraryAssetFile).not.toHaveBeenCalled();
  });
});

describe("AssetDetailDialog actor takes", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.mocked(listActorTakes).mockResolvedValue({ items: [] });
  });

  it("lists generation takes and pins a succeeded take onto the actor", async () => {
    vi.mocked(listActorTakes).mockResolvedValue({
      items: [
        { id: "actjob_1", status: "succeeded", created_at: "2026-01-01T00:00:00Z", pinned: false },
        { id: "actjob_2", status: "succeeded", created_at: "2026-01-02T00:00:00Z", pinned: true },
      ],
    });
    vi.mocked(pinActorTake).mockResolvedValue({
      ...actor,
      job_id: "actjob_1",
      meta: { pinned_take_job_id: "actjob_1" },
    });
    const onUpdated = vi.fn();
    render(<AssetDetailDialog asset={actor} onClose={() => undefined} onUpdated={onUpdated} />);

    expect(await screen.findByText("actjob_1")).toBeTruthy();
    expect(screen.getByText(/actjob_2/)).toBeTruthy();
    expect(screen.getByText(/pinned/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Pin" }));

    await waitFor(() => {
      expect(pinActorTake).toHaveBeenCalledWith("act_jenny", "actjob_1");
    });
    expect(onUpdated).toHaveBeenCalled();
  });

  it("does not show actor takes on a Voice asset", () => {
    render(
      <AssetDetailDialog
        asset={{
          ...actor,
          id: "voi_mia",
          kind: "voices",
          name: "Mia",
          files: { reference: "reference.wav" },
          urls: { reference: "/api/files/library/voices/voi_mia/reference.wav" },
        }}
        onClose={() => undefined}
      />,
    );
    expect(screen.queryByLabelText("Actor takes")).toBeNull();
    expect(listActorTakes).not.toHaveBeenCalled();
  });
});
