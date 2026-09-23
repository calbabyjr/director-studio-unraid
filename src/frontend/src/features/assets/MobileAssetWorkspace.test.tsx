// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Project } from "../../shared/api/types";
import { listLibraryAssets } from "../library/api";
import { MobileAssetWorkspace } from "./MobileAssetWorkspace";

const state = vi.hoisted(() => ({
  project: {
    id: "prj_1", name: "Night film", script_text: "", mode: "director",
    created_at: "2026-01-01", updated_at: "2026-01-01", shot_ids: [],
  } as Project | null,
}));

vi.mock("../../shared/project/ProjectContext", () => ({
  useProject: () => ({ project: state.project, projectId: state.project?.id ?? null }),
}));
vi.mock("../library/LibraryPage", () => ({
  LibraryPage: ({ lockedKind, mobile }: { lockedKind?: string; mobile?: boolean }) => (
    <div data-testid="mobile-library" data-kind={lockedKind} data-mobile={String(Boolean(mobile))} />
  ),
}));
vi.mock("../library/api", () => ({
  importExternalAsset: vi.fn(),
  recastLibraryAsset: vi.fn(),
  listActorTakes: vi.fn(async () => ({ items: [] })),
  pinActorTake: vi.fn(),
  listLibraryAssets: vi.fn(async (kind: string) => kind === "actors" ? [{
    id: "actor_1", kind: "actors", name: "Mara", notes: "Lead", pipeline_id: "external",
    job_id: "", seed: null, created_at: "2026-01-01", files: {}, meta: {},
    urls: { master: "/mara.png" }, project_id: "prj_1",
  }] : []),
}));
vi.mock("../casting/CastingPage", () => ({
  CastingPage: ({ active }: { active?: boolean }) => (
    <label>
      Actor generator
      <input aria-label="Mobile actor draft" />
      <span data-testid="mobile-casting-active">{active ? "yes" : "no"}</span>
    </label>
  ),
}));
vi.mock("../set/SetDesignPage", () => ({
  SetDesignPage: ({ active }: { active?: boolean }) => (
    <div>
      Scene generator
      <span data-testid="mobile-scene-active">{active ? "yes" : "no"}</span>
    </div>
  ),
}));
vi.mock("../props/PropsPage", () => ({
  PropsPage: ({ kind, active }: { kind?: string; active?: boolean }) => (
    <div>
      {kind === "costume" ? "Costume generator" : "Prop generator"}
      <span data-testid={kind === "costume" ? "mobile-costume-active" : "mobile-prop-active"}>
        {active ? "yes" : "no"}
      </span>
    </div>
  ),
}));

describe("MobileAssetWorkspace", () => {
  afterEach(cleanup);
  beforeEach(() => {
    state.project = {
      id: "prj_1", name: "Night film", script_text: "", mode: "director",
      created_at: "2026-01-01", updated_at: "2026-01-01", shot_ids: [],
    };
  });

  it("opens on a cross-category Library overview", async () => {
    render(<MobileAssetWorkspace />);

    for (const category of ["Library", "Actors", "Scenes", "Props", "Costumes", "Voices"]) {
      expect(screen.getByRole("button", { name: category })).toBeTruthy();
    }
    expect(screen.getByText("No wardrobe prepared")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Layouts" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Project library" })).toBeTruthy();
    await waitFor(() => expect(screen.getByText("Mara")).toBeTruthy());
    expect(screen.queryByTestId("mobile-library")).toBeNull();
  });

  it("reloads the project library after saving from a mobile preparation workflow", async () => {
    const mara = {
      id: "actor_1", kind: "actors", name: "Mara", notes: "Lead", pipeline_id: "actor",
      job_id: "job_1", seed: null, created_at: "2026-01-01", files: {}, meta: {},
      urls: { master: "/mara.png" }, project_id: "prj_1",
    };
    let actors: typeof mara[] = [];
    vi.mocked(listLibraryAssets).mockImplementation(async (kind: string) =>
      kind === "actors" ? actors : [],
    );
    render(<MobileAssetWorkspace />);

    await waitFor(() => expect(listLibraryAssets).toHaveBeenCalled());
    expect(screen.queryByText("Mara")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Actors" }));
    actors = [mara];
    fireEvent.click(screen.getByRole("button", { name: "Library" }));

    expect(await screen.findByText("Mara")).toBeTruthy();
    vi.mocked(listLibraryAssets).mockImplementation(async (kind: string) =>
      kind === "actors" ? [{
        id: "actor_1", kind: "actors", name: "Mara", notes: "Lead", pipeline_id: "external",
        job_id: "", seed: null, created_at: "2026-01-01", files: {}, meta: {},
        urls: { master: "/mara.png" }, project_id: "prj_1",
      }] : [],
    );
  });

  it("shows the preparation input directly without a category library", () => {
    render(<MobileAssetWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Actors" }));
    expect(screen.getByRole("heading", { name: "Actor workflow" })).toBeTruthy();
    expect(screen.getByText("Actor generator")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Import actor" })).toBeTruthy();
    expect(screen.queryByTestId("mobile-library")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Voices" }));
    expect(screen.getByRole("heading", { name: "Voice workflow" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Import voice" })).toBeTruthy();
    expect(screen.queryByTestId("mobile-library")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Costumes" }));
    expect(screen.getByRole("heading", { name: "Costume workflow" })).toBeTruthy();
    expect(screen.getByText("Costume generator")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Import costume" })).toBeTruthy();
    expect(screen.queryByTestId("mobile-library")).toBeNull();
  });

  it("does not show legacy coverage state", () => {
    state.project = {
      id: "prj_1", name: "Night film", script_text: "", mode: "director",
      created_at: "2026-01-01", updated_at: "2026-01-01", shot_ids: [],
      asset_coverage_review: { script_hash: "abc", status: "reviewed", recommendations: [], notes: "Ready" },
    };
    render(<MobileAssetWorkspace />);

    expect(screen.queryByText("Coverage reviewed")).toBeNull();
    expect(screen.queryByText("Coverage not reviewed")).toBeNull();
  });

  it("opens import from the labeled action inside a mobile category", () => {
    render(<MobileAssetWorkspace />);

    const categories = screen.getByRole("navigation", { name: "Asset categories" });
    expect(within(categories).queryByRole("button", { name: /Import/i })).toBeNull();
    fireEvent.click(within(categories).getByRole("button", { name: "Props" }));
    fireEvent.click(screen.getByRole("button", { name: "Import prop" }));

    expect(screen.getByRole("dialog", { name: "Import Props" })).toBeTruthy();
    expect(screen.queryByTestId("mobile-library")).toBeNull();
  });

  it("preserves an asset draft while switching mobile preparation categories", () => {
    render(<MobileAssetWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Actors" }));
    const draft = screen.getByRole("textbox", { name: "Mobile actor draft" });
    fireEvent.change(draft, { target: { value: "Keep this mobile reference" } });

    fireEvent.click(screen.getByRole("button", { name: "Props" }));
    fireEvent.click(screen.getByRole("button", { name: "Actors" }));

    expect((screen.getByRole("textbox", { name: "Mobile actor draft" }) as HTMLInputElement).value).toBe("Keep this mobile reference");
  });

  it("marks only the visible mobile preparation category as active", () => {
    render(<MobileAssetWorkspace />);

    expect(screen.getByTestId("mobile-casting-active").textContent).toBe("no");
    expect(screen.getByTestId("mobile-scene-active").textContent).toBe("no");
    expect(screen.getByTestId("mobile-prop-active").textContent).toBe("no");
    expect(screen.getByTestId("mobile-costume-active").textContent).toBe("no");

    fireEvent.click(screen.getByRole("button", { name: "Props" }));
    expect(screen.getByTestId("mobile-prop-active").textContent).toBe("yes");
    expect(screen.getByTestId("mobile-casting-active").textContent).toBe("no");
  });
});
