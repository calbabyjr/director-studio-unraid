// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ScriptDraftPanel } from "./ScriptDraftPanel";
import { updateProject } from "./api";
import type { Project } from "../../shared/api/types";

vi.mock("./api", () => ({
  updateProject: vi.fn(),
}));

const project: Project = {
  id: "prj_test",
  name: "W and J",
  script_text: "INT. CELL - NIGHT\n\nJENNY waits.",
  script_locked: false,
  script_draft_pending: true,
  mode: "director",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  shot_ids: [],
};

describe("ScriptDraftPanel", () => {
  afterEach(cleanup);

  it("locks the draft when approved", async () => {
    vi.mocked(updateProject).mockResolvedValue({
      ...project,
      script_locked: true,
      script_draft_pending: false,
    });
    const onUpdated = vi.fn();
    render(<ScriptDraftPanel project={project} onUpdated={onUpdated} />);
    expect(screen.getByLabelText("Screenplay")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Approve and lock" }));
    await waitFor(() => expect(updateProject).toHaveBeenCalled());
    expect(vi.mocked(updateProject).mock.calls[0][1]).toEqual({
      script_text: project.script_text,
      script_locked: true,
    });
    expect(onUpdated).toHaveBeenCalled();
  });

  it("keeps an existing screenplay collapsed until opened", () => {
    render(
      <ScriptDraftPanel
        project={{ ...project, script_draft_pending: false }}
      />,
    );
    expect(screen.queryByLabelText("Screenplay")).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve and lock" })).toBeNull();
    const toggle = screen.getByRole("button", { name: "Toggle screenplay" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByLabelText("Screenplay")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve and lock" })).toBeTruthy();
  });

  it("keeps the screenplay toggle name stable after toggling", () => {
    render(
      <ScriptDraftPanel
        project={{ ...project, script_draft_pending: false }}
      />,
    );
    const toggle = screen.getByRole("button", { name: "Toggle screenplay" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Toggle screenplay" })).toBe(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Toggle screenplay" })).toBe(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });
});
