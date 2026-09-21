// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectProvider, useProject } from "./ProjectContext";
import { ProjectPicker } from "./ProjectPicker";

const emptyProject = {
  id: "prj_e44cb3faa9eb",
  name: "Testing props2",
  script_text: "",
  mode: "director" as const,
  created_at: "2026-09-20T23:04:51.619712+00:00",
  updated_at: "2026-09-20T23:04:51.619749+00:00",
  shot_ids: [],
};

const fullProject = {
  id: "prj_1f0013110fe0",
  name: "Testing 1.0",
  script_text: "Jenny and Wendy.",
  mode: "director" as const,
  created_at: "2026-09-19T00:37:44.056992+00:00",
  updated_at: "2026-09-19T00:37:44.056992+00:00",
  shot_ids: ["sht_1"],
};

const listProjects = vi.fn();
const updateProject = vi.fn();
const createProject = vi.fn();

vi.mock("../../features/director/api", () => ({
  listProjects: (...args: unknown[]) => listProjects(...args),
  updateProject: (...args: unknown[]) => updateProject(...args),
  createProject: (...args: unknown[]) => createProject(...args),
}));

function ActiveProjectProbe() {
  const { projectId, project } = useProject();
  return (
    <div>
      <span data-testid="active-id">{projectId}</span>
      <span data-testid="active-name">{project?.name}</span>
    </div>
  );
}

describe("ProjectContext rename", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.setItem("ds.activeProjectId", fullProject.id);
    let projects = [emptyProject, fullProject];
    listProjects.mockImplementation(async () => projects);
    updateProject.mockImplementation(async (_id: string, body: { name: string }) => {
      const updated = {
        ...fullProject,
        name: body.name,
        updated_at: "2026-09-21T00:17:34.202684+00:00",
      };
      projects = [emptyProject, updated];
      return updated;
    });
  });

  it("renames in place and does not select another project", async () => {
    render(
      <ProjectProvider>
        <ProjectPicker />
        <ActiveProjectProbe />
      </ProjectProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("active-id").textContent).toBe(fullProject.id));
    const select = screen.getByLabelText("Project") as HTMLSelectElement;
    expect(select.value).toBe(fullProject.id);
    expect(select.querySelector("option")?.value).toBe(fullProject.id);

    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("Project name"), {
      target: { value: "W and J evenings 1.0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(updateProject).toHaveBeenCalledWith(fullProject.id, {
        name: "W and J evenings 1.0",
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("active-name").textContent).toBe("W and J evenings 1.0"),
    );
    expect(screen.getByTestId("active-id").textContent).toBe(fullProject.id);
    expect((screen.getByLabelText("Project") as HTMLSelectElement).value).toBe(fullProject.id);
  });
});
