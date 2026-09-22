// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkspaceFilesSetup } from "./WorkspaceFilesSetup";

const projectState = vi.hoisted(() => ({
  projectId: "prj_1" as string | null,
}));

vi.mock("../../shared/project/ProjectContext", () => ({
  useProject: () => ({
    projectId: projectState.projectId,
    project: projectState.projectId ? { id: projectState.projectId } : null,
    refreshProjects: vi.fn(),
  }),
}));

vi.mock("../director/api", () => ({
  listWorkspaceFiles: vi.fn(),
  createWorkspaceFile: vi.fn(),
  saveWorkspaceFile: vi.fn(),
  deleteWorkspaceFile: vi.fn(),
}));

import {
  createWorkspaceFile,
  listWorkspaceFiles,
  saveWorkspaceFile,
} from "../director/api";

const agents = {
  name: "AGENTS.md",
  scope: "global" as const,
  markdown: "# Studio\n\nAlways shoot handheld.\n",
  reserved: true,
  placeholder: false,
  updated_at: "2026-09-21T00:00:00Z",
};

describe("WorkspaceFilesSetup", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    projectState.projectId = "prj_1";
  });

  it("hides user.md and saves an extra studio file", async () => {
    vi.mocked(listWorkspaceFiles).mockResolvedValue([
      {
        name: "user.md",
        scope: "global",
        markdown: "# User",
        reserved: true,
        placeholder: false,
        updated_at: "2026-09-21T00:00:00Z",
      },
      agents,
    ]);
    vi.mocked(saveWorkspaceFile).mockResolvedValue({
      ...agents,
      markdown: "# Studio\n\nAlways shoot handheld.\nKeep eyelines.\n",
    });
    render(<WorkspaceFilesSetup scope="global" />);

    const editor = await screen.findByLabelText("AGENTS.md");
    expect(screen.queryByRole("option", { name: /user.md/ })).toBeNull();
    fireEvent.change(editor, {
      target: { value: "# Studio\n\nAlways shoot handheld.\nKeep eyelines.\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save AGENTS.md" }));

    await waitFor(() => {
      expect(saveWorkspaceFile).toHaveBeenCalledWith(
        "AGENTS.md",
        expect.stringContaining("Keep eyelines"),
        "global",
        null,
        null,
      );
    });
  });

  it("creates an extra workspace file", async () => {
    vi.mocked(listWorkspaceFiles).mockResolvedValue([agents]);
    vi.mocked(createWorkspaceFile).mockResolvedValue({
      name: "house-style.md",
      scope: "global",
      markdown: "",
      reserved: false,
      placeholder: true,
      updated_at: "2026-09-21T00:00:00Z",
    });
    render(<WorkspaceFilesSetup scope="global" />);
    await screen.findByLabelText("AGENTS.md");
    fireEvent.change(screen.getByPlaceholderText("house-style.md"), {
      target: { value: "house-style.md" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => {
      expect(createWorkspaceFile).toHaveBeenCalledWith({
        name: "house-style.md",
        scope: "global",
        projectId: null,
        soulId: null,
      });
    });
  });

  it("asks for a project before editing production files", async () => {
    projectState.projectId = null;
    render(<WorkspaceFilesSetup scope="project" />);
    expect(await screen.findByText(/Open a project to edit this production/)).toBeTruthy();
    expect(listWorkspaceFiles).not.toHaveBeenCalled();
  });
});
