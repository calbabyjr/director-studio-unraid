// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssetDetailDialog } from "./AssetDetailDialog";
import {
  addActorVoiceSample,
  addLibraryAssetFile,
  deleteLibraryAssetFile,
  getActorJob,
  getLibraryAsset,
  listActorTakes,
  pinActorTake,
  updateActorSheet,
  updateLibraryAsset,
  type LibraryAsset,
} from "./api";

vi.mock("./api", () => ({
  addLibraryAssetFile: vi.fn(),
  deleteLibraryAssetFile: vi.fn(),
  addActorVoiceSample: vi.fn(),
  listActorTakes: vi.fn(async () => ({ items: [] })),
  pinActorTake: vi.fn(),
  updateActorSheet: vi.fn(),
  updateLibraryAsset: vi.fn(),
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
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.mocked(window.confirm)?.mockRestore?.();
    vi.mocked(getActorJob).mockResolvedValue({ id: "job_sheet", status: "queued", error: null });
    vi.mocked(listActorTakes).mockResolvedValue({ items: [] });
  });

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
    await waitFor(() => expect(updateActorSheet).toHaveBeenCalledWith("act_jenny", { dress_state: "unclothed" }));
    expect(screen.getByText(/Sheet job queued/)).toBeTruthy();
  });

  it("keeps actor image and sheet actions on two toolbar rows", () => {
    const { container } = render(<AssetDetailDialog asset={actor} onClose={() => undefined} />);
    const imageRow = container.querySelector(".folder-add-image:not(.folder-actor-sheet-actions)");
    const sheetRow = container.querySelector(".folder-actor-sheet-actions");
    expect(imageRow).toBeTruthy();
    expect(sheetRow).toBeTruthy();
    expect(imageRow?.contains(screen.getByRole("button", { name: "Add image" }))).toBe(true);
    expect(sheetRow?.contains(screen.getByRole("button", { name: "Update asset sheet" }))).toBe(true);
    expect(sheetRow?.contains(screen.getByRole("button", { name: "Add voice sample" }))).toBe(true);
    expect((screen.getByLabelText("Body") as HTMLSelectElement).value).toBe("unclothed");
  });

  it("adds an extra identity still onto the actor folder", async () => {
    vi.mocked(addLibraryAssetFile).mockResolvedValue({
      ...actor,
      files: { master: "master.png", profile: "profile.png" },
      urls: {
        master: "/api/files/library/actors/act_jenny/master.png",
        profile: "/api/files/library/actors/act_jenny/profile.png",
      },
    });
    const onUpdated = vi.fn();
    render(<AssetDetailDialog asset={actor} onClose={() => undefined} onUpdated={onUpdated} />);

    fireEvent.change(screen.getByLabelText("New actor view"), { target: { value: "profile" } });
    fireEvent.change(screen.getByLabelText("Actor view file"), {
      target: { files: [new File(["jpg"], "profile.jpg", { type: "image/jpeg" })] },
    });

    await waitFor(() => expect(addLibraryAssetFile).toHaveBeenCalledOnce());
    expect(addLibraryAssetFile).toHaveBeenCalledWith(
      "actors",
      "act_jenny",
      expect.any(File),
      "profile",
    );
    expect(onUpdated).toHaveBeenCalled();
    expect(screen.getByRole("img", { name: "Profile" })).toBeTruthy();
  });

  it("deletes a clothed identity JPEG from the actor folder", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const withFace: LibraryAsset = {
      ...actor,
      files: { master: "master.png", face: "face.jpg" },
      urls: {
        master: "/api/files/library/actors/act_jenny/master.png",
        face: "/api/files/library/actors/act_jenny/face.jpg",
      },
    };
    vi.mocked(deleteLibraryAssetFile).mockResolvedValue({
      ...actor,
      files: { master: "master.png" },
      urls: { master: "/api/files/library/actors/act_jenny/master.png" },
    });
    const onUpdated = vi.fn();
    render(<AssetDetailDialog asset={withFace} onClose={() => undefined} onUpdated={onUpdated} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete Face" }));
    await waitFor(() => expect(deleteLibraryAssetFile).toHaveBeenCalledWith("actors", "act_jenny", "face"));
    expect(window.confirm).toHaveBeenCalled();
    expect(onUpdated).toHaveBeenCalled();
    expect(screen.queryByRole("img", { name: "Face" })).toBeNull();
    expect(screen.getByRole("img", { name: "Master" })).toBeTruthy();
  });

  it("persists a clothed body choice from the actor folder", async () => {
    vi.mocked(updateLibraryAsset).mockResolvedValue({
      ...actor,
      meta: { dress_state: "clothed" },
    });
    const onUpdated = vi.fn();
    render(<AssetDetailDialog asset={actor} onClose={() => undefined} onUpdated={onUpdated} />);
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "clothed" } });
    await waitFor(() => expect(updateLibraryAsset).toHaveBeenCalledWith(
      "actors",
      "act_jenny",
      { dress_state: "clothed" },
    ));
    expect(onUpdated).toHaveBeenCalled();
  });

  it("refreshes folder files after an asset-sheet job succeeds", async () => {
    vi.mocked(updateActorSheet).mockResolvedValue({
      id: "job_sheet",
      status: "queued",
      error: null,
    });
    vi.mocked(getLibraryAsset).mockResolvedValue({
      ...actor,
      files: { master: "master.png", fullbody_threeview: "full.png" },
      urls: {
        master: "/api/files/library/actors/act_jenny/master.png",
        fullbody_threeview: "/api/files/library/actors/act_jenny/full.png",
      },
    });
    vi.mocked(getActorJob).mockResolvedValue({
      id: "job_sheet",
      status: "succeeded",
      error: null,
    });
    const onUpdated = vi.fn();
    render(<AssetDetailDialog asset={actor} onClose={() => undefined} onUpdated={onUpdated} />);
    fireEvent.click(screen.getByRole("button", { name: "Update asset sheet" }));
    await waitFor(() => expect(getLibraryAsset).toHaveBeenCalledWith("actors", "act_jenny"));
    expect(onUpdated).toHaveBeenCalled();
    expect(screen.getByText("Full-body three-view")).toBeTruthy();
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

  it("renders the file grid before the takes list", async () => {
    vi.mocked(listActorTakes).mockResolvedValue({
      items: [
        { id: "actjob_1", status: "succeeded", created_at: "2026-01-01T00:00:00Z", pinned: false },
      ],
    });
    render(<AssetDetailDialog asset={actor} onClose={() => undefined} />);
    const master = await screen.findByText("Master");
    const takes = screen.getByLabelText("Actor takes");
    expect(master.compareDocumentPosition(takes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
