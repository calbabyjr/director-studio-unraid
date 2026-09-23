// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Project } from "../../shared/api/types";
import { getScreenplayInterview, postScreenplayInterview } from "./api";
import { ScreenplayInterviewPanel } from "./ScreenplayInterviewPanel";

vi.mock("./api", () => ({
  getScreenplayInterview: vi.fn(),
  postScreenplayInterview: vi.fn(),
}));

const project: Project = {
  id: "prj_ideas",
  name: "Ideas",
  script_text: "",
  mode: "director",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  shot_ids: [],
};

describe("ScreenplayInterviewPanel", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("sends ideas and shows the writer's question", async () => {
    vi.mocked(getScreenplayInterview).mockResolvedValue({
      premise: "",
      turns: [],
      ready: false,
      brief: "",
      updated_at: "",
    });
    vi.mocked(postScreenplayInterview).mockResolvedValue({
      premise: "Two women in a dungeon.",
      turns: [
        { role: "user", content: "Two women in a dungeon." },
        { role: "assistant", content: "What do they want tonight?" },
      ],
      ready: false,
      brief: "",
      updated_at: "",
    });
    render(<ScreenplayInterviewPanel project={project} />);
    await waitFor(() => expect(getScreenplayInterview).toHaveBeenCalledWith("prj_ideas"));
    fireEvent.change(screen.getByLabelText("Screenplay ideas"), {
      target: { value: "Two women in a dungeon." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start interview" }));
    await waitFor(() => expect(postScreenplayInterview).toHaveBeenCalled());
    expect(vi.mocked(postScreenplayInterview).mock.calls[0][1]).toEqual({
      message: "Two women in a dungeon.",
    });
    expect(screen.getByText("What do they want tonight?")).toBeTruthy();
  });

  it("hides the interview once pages already exist", () => {
    render(
      <ScreenplayInterviewPanel
        project={{ ...project, script_text: "INT. DUNGEON - NIGHT" }}
      />,
    );
    expect(screen.queryByLabelText("Screenplay interview")).toBeNull();
    expect(getScreenplayInterview).not.toHaveBeenCalled();
  });

  it("writes the screenplay from the interview", async () => {
    const onDrafted = vi.fn();
    vi.mocked(getScreenplayInterview).mockResolvedValue({
      premise: "Jenny and Wendy.",
      turns: [{ role: "user", content: "Jenny and Wendy." }],
      ready: true,
      brief: "A short dungeon scene.",
      updated_at: "",
    });
    vi.mocked(postScreenplayInterview).mockResolvedValue({
      premise: "Jenny and Wendy.",
      turns: [],
      ready: true,
      brief: "A short dungeon scene.",
      updated_at: "",
      drafted: true,
      script_text: "INT. DUNGEON - NIGHT",
    });
    render(<ScreenplayInterviewPanel project={project} onDrafted={onDrafted} />);
    await waitFor(() => expect(getScreenplayInterview).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Write the screenplay" }));
    await waitFor(() => expect(postScreenplayInterview).toHaveBeenCalledWith("prj_ideas", { generate: true, message: undefined }));
    expect(onDrafted).toHaveBeenCalled();
  });
});
