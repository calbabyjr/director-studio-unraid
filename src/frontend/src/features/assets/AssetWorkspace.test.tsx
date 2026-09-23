// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Project } from "../../shared/api/types";
import { listLibraryAssets } from "../library/api";
import { AssetWorkspace } from "./AssetWorkspace";

const state = vi.hoisted(() => ({ project: null as Project | null }));

vi.mock("../../shared/project/ProjectContext", () => ({
  useProject: () => ({ project: state.project, projectId: state.project?.id ?? null }),
}));
vi.mock("../library/LibraryPage", () => ({
  LibraryPage: ({ lockedKind }: { lockedKind?: string }) => (
    <div data-testid="asset-library">Library:{lockedKind}</div>
  ),
}));
vi.mock("../casting/CastingPage", () => ({
  CastingPage: ({ active }: { active?: boolean }) => (
    <label>
      Actor preparation tool
      <input aria-label="Actor draft" />
      <span data-testid="casting-active">{active ? "yes" : "no"}</span>
    </label>
  ),
}));
vi.mock("../set/SetDesignPage", () => ({
  SetDesignPage: ({ active }: { active?: boolean }) => (
    <div>
      Scene preparation tool
      <span data-testid="scene-active">{active ? "yes" : "no"}</span>
    </div>
  ),
}));
vi.mock("../props/PropsPage", () => ({
  PropsPage: ({ kind, active }: { kind?: string; active?: boolean }) => (
    <div>
      {kind === "costume" ? "Costume preparation tool" : "Prop preparation tool"}
      <span data-testid={kind === "costume" ? "costume-active" : "prop-active"}>{active ? "yes" : "no"}</span>
    </div>
  ),
}));
vi.mock("../library/api", () => ({
  importExternalAsset: vi.fn(),
  recastLibraryAsset: vi.fn(),
  addLibraryAssetFile: vi.fn(),
  addActorVoiceSample: vi.fn(),
  listActorTakes: vi.fn(async () => ({ items: [] })),
  pinActorTake: vi.fn(),
  listLibraryAssets: vi.fn(async (kind: string) => kind === "actors" ? [{
    id: "actor_1", kind: "actors", name: "Mara", notes: "Lead", pipeline_id: "external",
    job_id: "", seed: null, created_at: "2026-01-01", files: {}, meta: {},
    urls: { master: "/mara.png" }, project_id: "prj_1",
  }] : []),
}));

describe("AssetWorkspace", () => {
  afterEach(cleanup);

  it("opens on a project-wide Library and keeps Layouts out of Assets", async () => {
    state.project = {
      id: "prj_1", name: "Film", script_text: "", mode: "director",
      created_at: "2026-01-01", updated_at: "2026-01-01", shot_ids: [],
    };
    render(<AssetWorkspace />);

    expect(screen.queryByText("Step 01 · Prepare the visual language")).toBeNull();
    expect(screen.getByRole("button", { name: "Library" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Actors" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Costumes" })).toBeTruthy();
    expect(screen.getByText("No wardrobe prepared")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Scenes" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Props" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Voices" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Layouts" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Project library" })).toBeTruthy();
    expect(await screen.findByText("Mara")).toBeTruthy();
    const overview = screen.getByRole("heading", { name: "Project library" }).closest(".library-overview");
    expect(overview).toBeTruthy();
    fireEvent.click(within(overview as HTMLElement).getByRole("button", { name: "Import Actors" }));
    expect(screen.getByRole("dialog", { name: "Import Actors" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close import" }));

    fireEvent.click(screen.getByRole("button", { name: "Scenes" }));
    expect(screen.queryByTestId("asset-library")).toBeNull();
    expect(screen.getByText("Scene preparation tool")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Import scene" })).toBeTruthy();
  });

  it("does not turn legacy coverage metadata into an Assets workflow", () => {
    state.project = {
      id: "prj_1", name: "Film", script_text: "", mode: "director",
      created_at: "2026-01-01", updated_at: "2026-01-01", shot_ids: [],
      asset_coverage_review: {
        script_hash: "abc", status: "reviewed", notes: "Core cast is ready.",
        recommendations: [{
          kind: "actor", asset_id: "act_1", needed_variant: "Rear silhouette",
          reason: "Needed for the reveal", shot_ids: ["sht_2"], priority: "high",
          resolution: "pending",
        }],
      },
    };
    render(<AssetWorkspace />);

    expect(screen.queryByText("Coverage reviewed")).toBeNull();
    expect(screen.queryByText("Rear silhouette")).toBeNull();
    expect(screen.queryByText("Needed for the reveal")).toBeNull();
    expect(screen.queryByText(/advisory/i)).toBeNull();
  });

  it("keeps category navigation separate from the explicit import action", () => {
    state.project = {
      id: "prj_1", name: "Film", script_text: "", mode: "director",
      created_at: "2026-01-01", updated_at: "2026-01-01", shot_ids: [],
    };
    render(<AssetWorkspace />);

    const categories = screen.getByRole("navigation", { name: "Asset categories" });
    expect(within(categories).queryByRole("button", { name: /Import/i })).toBeNull();
    fireEvent.click(within(categories).getByRole("button", { name: "Scenes" }));
    fireEvent.click(screen.getByRole("button", { name: "Import scene" }));

    expect(screen.getByRole("dialog", { name: "Import Scenes" })).toBeTruthy();
    expect(screen.queryByTestId("asset-library")).toBeNull();
  });

  it("reloads the project library after saving from a preparation workflow", async () => {
    const mara = {
      id: "actor_1", kind: "actors", name: "Mara", notes: "Lead", pipeline_id: "actor",
      job_id: "job_1", seed: null, created_at: "2026-01-01", files: {}, meta: {},
      urls: { master: "/mara.png" }, project_id: "prj_1",
    };
    let actors: typeof mara[] = [];
    vi.mocked(listLibraryAssets).mockImplementation(async (kind: string) =>
      kind === "actors" ? actors : [],
    );
    state.project = {
      id: "prj_1", name: "Film", script_text: "", mode: "director",
      created_at: "2026-01-01", updated_at: "2026-01-01", shot_ids: [],
    };
    render(<AssetWorkspace />);

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

  it("preserves an asset draft while switching preparation categories", () => {
    state.project = {
      id: "prj_1", name: "Film", script_text: "", mode: "director",
      created_at: "2026-01-01", updated_at: "2026-01-01", shot_ids: [],
    };
    render(<AssetWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Actors" }));
    const draft = screen.getByRole("textbox", { name: "Actor draft" }) as HTMLInputElement;
    fireEvent.change(draft, { target: { value: "Mia close-up reference" } });

    fireEvent.click(screen.getByRole("button", { name: "Scenes" }));
    fireEvent.click(screen.getByRole("button", { name: "Actors" }));

    expect((screen.getByRole("textbox", { name: "Actor draft" }) as HTMLInputElement).value).toBe("Mia close-up reference");
  });

  it("marks only the visible preparation category as active", () => {
    state.project = {
      id: "prj_1", name: "Film", script_text: "", mode: "director",
      created_at: "2026-01-01", updated_at: "2026-01-01", shot_ids: [],
    };
    render(<AssetWorkspace />);

    expect(screen.getByTestId("casting-active").textContent).toBe("no");
    expect(screen.getByTestId("scene-active").textContent).toBe("no");
    expect(screen.getByTestId("prop-active").textContent).toBe("no");
    expect(screen.getByTestId("costume-active").textContent).toBe("no");

    fireEvent.click(screen.getByRole("button", { name: "Actors" }));
    expect(screen.getByTestId("casting-active").textContent).toBe("yes");
    expect(screen.getByTestId("scene-active").textContent).toBe("no");

    fireEvent.click(screen.getByRole("button", { name: "Scenes" }));
    expect(screen.getByTestId("casting-active").textContent).toBe("no");
    expect(screen.getByTestId("scene-active").textContent).toBe("yes");
  });

  it("opens a costume preparation workflow", () => {
    state.project = {
      id: "prj_1", name: "Film", script_text: "", mode: "director",
      created_at: "2026-01-01", updated_at: "2026-01-01", shot_ids: [],
    };
    render(<AssetWorkspace />);

    fireEvent.click(screen.getByRole("button", { name: "Costumes" }));
    expect(screen.getByText("Costume preparation tool")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Import costume" }));
    expect(screen.getByRole("dialog", { name: "Import Costumes" })).toBeTruthy();
  });
});
