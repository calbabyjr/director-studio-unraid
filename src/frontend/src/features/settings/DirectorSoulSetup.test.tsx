// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DirectorSoulSetup } from "./DirectorSoulSetup";

const projectState = vi.hoisted(() => ({
  projectId: "prj_1" as string | null,
  project: { id: "prj_1", soul_id: "adult-video" } as { id: string; soul_id: string } | null,
}));

vi.mock("../../shared/project/ProjectContext", () => ({
  useProject: () => ({
    projectId: projectState.projectId,
    project: projectState.project,
    refreshProjects: vi.fn(),
  }),
}));

vi.mock("../director/api", () => ({
  listDirectorSouls: vi.fn(),
  createDirectorSoul: vi.fn(),
  saveDirectorSoul: vi.fn(),
  deleteDirectorSoul: vi.fn(),
  updateProject: vi.fn(),
}));

import {
  createDirectorSoul,
  listDirectorSouls,
  saveDirectorSoul,
  updateProject,
} from "../director/api";

const adult = {
  id: "adult-video",
  name: "Adult video director",
  description: "Explicit adult production",
  builtin: true,
  markdown: "# Adult video director\n\nKeep identities exact.",
  lessons: "- Do not invent extra performers",
  updated_at: "2026-09-21T00:00:00Z",
};

describe("DirectorSoulSetup", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    projectState.projectId = "prj_1";
    projectState.project = { id: "prj_1", soul_id: "adult-video" };
  });

  it("loads soul.md for editing and saves it", async () => {
    vi.mocked(listDirectorSouls).mockResolvedValue([adult]);
    vi.mocked(saveDirectorSoul).mockResolvedValue({
      ...adult,
      markdown: "# Adult video director\n\nKeep identities exact.\nNever swap roles.",
    });
    render(<DirectorSoulSetup />);

    const editor = await screen.findByLabelText("soul.md");
    expect((editor as HTMLTextAreaElement).value).toContain("Keep identities exact.");
    fireEvent.change(editor, {
      target: { value: "# Adult video director\n\nKeep identities exact.\nNever swap roles." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save soul" }));

    await waitFor(() => {
      expect(saveDirectorSoul).toHaveBeenCalledWith("adult-video", expect.objectContaining({
        markdown: expect.stringContaining("Never swap roles"),
      }));
    });
  });

  it("creates a soul without a project selected", async () => {
    projectState.projectId = null;
    projectState.project = null;
    vi.mocked(listDirectorSouls).mockResolvedValue([adult]);
    vi.mocked(createDirectorSoul).mockResolvedValue({
      id: "horror-director",
      name: "Horror director",
      description: "",
      builtin: false,
      markdown: "# Horror director",
      lessons: "",
      updated_at: "2026-09-21T00:00:00Z",
    });
    render(<DirectorSoulSetup />);
    await screen.findByLabelText("soul.md");
    fireEvent.change(screen.getByPlaceholderText("Horror director"), {
      target: { value: "Horror director" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => {
      expect(createDirectorSoul).toHaveBeenCalledWith({ name: "Horror director" });
    });
  });

  it("binds the selected soul to the current project", async () => {
    vi.mocked(listDirectorSouls).mockResolvedValue([adult]);
    vi.mocked(updateProject).mockResolvedValue({} as never);
    render(<DirectorSoulSetup />);
    await screen.findByLabelText("soul.md");
    fireEvent.click(screen.getByRole("button", { name: "Use on this project" }));
    await waitFor(() => {
      expect(updateProject).toHaveBeenCalledWith("prj_1", { soul_id: "adult-video" });
    });
  });
});
