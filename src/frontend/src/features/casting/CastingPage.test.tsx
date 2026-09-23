// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CastingPage } from "./CastingPage";
import { fetchDefaults, generateActor, getJob, listActorJobs, saveJob, type JobRecord } from "./api";
import { listActorTakes } from "../library/api";

vi.mock("../../shared/project/ProjectContext", () => ({
  useProject: () => ({ projectId: "prj_test" }),
}));

vi.mock("./api", () => ({
  fetchDefaults: vi.fn(),
  listActorJobs: vi.fn(),
  generateActor: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  saveJob: vi.fn(),
}));

vi.mock("../library/api", () => ({
  addLibraryAssetFile: vi.fn(),
  addActorVoiceSample: vi.fn(),
  listActorTakes: vi.fn(async () => ({ items: [] })),
  pinActorTake: vi.fn(),
}));

const finishedJob: JobRecord = {
  id: "actjob_old",
  status: "succeeded",
  mode: "text",
  name: "Discarded actor result",
  notes: "",
  description: "",
  body_description: "",
  hair_description: "",
  negative_prompt: "",
  has_actor_ref: false,
  has_wardrobe_ref: false,
  include_headwear: false,
  include_footwear: false,
  seed: 42,
  fixed_seed: false,
  error: null,
  comfy_prompt_id: "prompt_old",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:01:00Z",
  outputs: {},
  input_previews: {},
  actor_id: null,
};

describe("CastingPage", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchDefaults).mockResolvedValue({
      default_negative: "",
      default_description: "",
      max_upload_mb: 20,
      output_slots: [],
    });
    vi.mocked(listActorJobs).mockResolvedValue([]);
  });

  it("does not fetch defaults or jobs while the category is hidden", async () => {
    render(<CastingPage active={false} onOpenLibrary={() => undefined} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetchDefaults).not.toHaveBeenCalled();
    expect(listActorJobs).not.toHaveBeenCalled();
  });

  it("does not poll an in-flight actor job while the category is hidden", async () => {
    const running: JobRecord = { ...finishedJob, id: "actjob_run", status: "running", name: "Jenny" };
    vi.mocked(listActorJobs).mockResolvedValue([running]);
    vi.mocked(getJob).mockResolvedValue(running);

    const { rerender } = render(<CastingPage onOpenLibrary={() => undefined} />);
    expect(await screen.findByText("Running workbench…")).toBeTruthy();

    vi.useFakeTimers();
    rerender(<CastingPage active={false} onOpenLibrary={() => undefined} />);
    vi.mocked(getJob).mockClear();
    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getJob).not.toHaveBeenCalled();
  });

  it("polls an in-flight actor job only while the category is visible", async () => {
    const running: JobRecord = { ...finishedJob, id: "actjob_run", status: "running", name: "Jenny" };
    vi.mocked(listActorJobs).mockResolvedValue([running]);
    vi.mocked(getJob).mockResolvedValue(running);
    vi.useFakeTimers();

    render(<CastingPage onOpenLibrary={() => undefined} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Running workbench…")).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getJob).toHaveBeenCalledWith("actjob_run");
  });

  it("does not restore an old finished actor job as the current result", async () => {
    vi.mocked(listActorJobs).mockResolvedValue([finishedJob]);

    render(<CastingPage onOpenLibrary={() => undefined} />);
    await waitFor(() => expect(listActorJobs).toHaveBeenCalled());

    expect((screen.getByLabelText(/Name/) as HTMLInputElement).value).toBe("");
    expect(screen.queryByText("actjob_old")).toBeNull();
    expect(screen.getByText("Idle")).toBeTruthy();
  });

  it("offers wardrobe accessory options and submits them", async () => {
    vi.mocked(generateActor).mockResolvedValue({
      ...finishedJob,
      id: "actjob_new",
      status: "queued",
      name: "Pirate Mia",
      has_wardrobe_ref: true,
      include_headwear: true,
      include_footwear: true,
    });

    render(<CastingPage onOpenLibrary={() => undefined} />);
    await waitFor(() => expect(fetchDefaults).toHaveBeenCalled());

    expect(screen.queryByLabelText("Include hat / headwear")).toBeNull();
    const wardrobeInput = screen.getByLabelText("Wardrobe") as HTMLInputElement;
    fireEvent.change(wardrobeInput, {
      target: { files: [new File(["wardrobe"], "pirate.png", { type: "image/png" })] },
    });

    fireEvent.click(screen.getByLabelText("Include hat / headwear"));
    fireEvent.click(screen.getByLabelText("Include shoes / footwear"));
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: "Pirate Mia" } });
    fireEvent.change(screen.getByLabelText(/Actor description/), {
      target: { value: "Adult pirate actor" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate Actor" }));

    await waitFor(() => expect(generateActor).toHaveBeenCalledOnce());
    const form = vi.mocked(generateActor).mock.calls[0][0];
    expect(form.get("include_headwear")).toBe("true");
    expect(form.get("include_footwear")).toBe("true");
  });

  it("sends extra identity photos with generate so they feed the Asset Sheet", async () => {
    vi.mocked(generateActor).mockResolvedValue({
      ...finishedJob,
      id: "actjob_sheet",
      status: "queued",
      name: "Jenny",
      has_actor_ref: true,
    });

    render(<CastingPage onOpenLibrary={() => undefined} />);
    await waitFor(() => expect(fetchDefaults).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: "Jenny" } });
    fireEvent.change(screen.getByLabelText("Actor") as HTMLInputElement, {
      target: { files: [new File(["front"], "front.png", { type: "image/png" })] },
    });
    fireEvent.change(screen.getByLabelText("Face") as HTMLInputElement, {
      target: { files: [new File(["face"], "face.png", { type: "image/png" })] },
    });
    fireEvent.change(screen.getByLabelText("Back") as HTMLInputElement, {
      target: { files: [new File(["back"], "back.png", { type: "image/png" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate Actor" }));

    await waitFor(() => expect(generateActor).toHaveBeenCalledOnce());
    const form = vi.mocked(generateActor).mock.calls[0][0];
    expect((form.get("actor_image") as File).name).toBe("front.png");
    expect((form.get("face_image") as File).name).toBe("face.png");
    expect((form.get("back_image") as File).name).toBe("back.png");
    expect(form.get("profile_image")).toBeNull();
    expect(form.get("dress_state")).toBe("unclothed");
  });

  it("places Body beside Name and submits a clothed dress state", async () => {
    vi.mocked(generateActor).mockResolvedValue({
      ...finishedJob,
      id: "actjob_body",
      status: "queued",
      name: "Jenny",
    });
    render(<CastingPage onOpenLibrary={() => undefined} />);
    await waitFor(() => expect(fetchDefaults).toHaveBeenCalled());
    expect((screen.getByLabelText("Body") as HTMLSelectElement).value).toBe("unclothed");
    expect(screen.getByLabelText("Extra three-view")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "clothed" } });
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: "Jenny" } });
    fireEvent.change(screen.getByLabelText(/Actor description/), {
      target: { value: "Adult actor" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate Actor" }));
    await waitFor(() => expect(generateActor).toHaveBeenCalledOnce());
    expect(vi.mocked(generateActor).mock.calls[0][0].get("dress_state")).toBe("clothed");
  });

  it("offers a voice sample upload on the actor form", async () => {
    render(<CastingPage onOpenLibrary={() => undefined} />);
    await waitFor(() => expect(fetchDefaults).toHaveBeenCalled());
    const input = screen.getByLabelText("Voice sample") as HTMLInputElement;
    expect(input.accept).toContain("audio");
    fireEvent.change(input, {
      target: { files: [new File(["voice"], "jenny.wav", { type: "audio/wav" })] },
    });
    expect(screen.getByText("jenny.wav")).toBeTruthy();
  });

  it("lists actor takes after save so a generation can be pinned", async () => {
    vi.mocked(generateActor).mockResolvedValue({
      ...finishedJob,
      id: "actjob_new",
      status: "succeeded",
      name: "Jenny",
    });
    vi.mocked(saveJob).mockResolvedValue({
      id: "act_jenny",
      name: "Jenny",
      notes: "",
      mode: "text",
      description: "",
      seed: 42,
      job_id: "actjob_new",
      created_at: "2026-01-01T00:00:00Z",
      files: {},
      urls: {},
      project_id: "prj_test",
    });
    vi.mocked(listActorTakes).mockResolvedValue({
      items: [
        { id: "actjob_new", status: "succeeded", created_at: "2026-01-01T00:00:00Z", pinned: true },
        { id: "actjob_old", status: "succeeded", created_at: "2026-01-01T00:00:00Z", pinned: false },
      ],
    });

    render(<CastingPage onOpenLibrary={() => undefined} />);
    await waitFor(() => expect(fetchDefaults).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: "Jenny" } });
    fireEvent.change(screen.getByLabelText(/Actor description/), {
      target: { value: "Adult actor" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate Actor" }));
    await waitFor(() => expect(generateActor).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole("button", { name: "Save to Library" }));

    expect(await screen.findByLabelText("Actor takes")).toBeTruthy();
    expect(await screen.findByText("actjob_new")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Pin" })).toBeTruthy();
  });
});
