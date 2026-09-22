// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DirectorMemorySetup } from "./DirectorMemorySetup";

vi.mock("../director/api", () => ({
  getDirectorMemoryDocument: vi.fn(),
  saveDirectorMemoryDocument: vi.fn(),
}));

import { getDirectorMemoryDocument, saveDirectorMemoryDocument } from "../director/api";

describe("DirectorMemorySetup", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("loads MEMORY.md and saves edits", async () => {
    vi.mocked(getDirectorMemoryDocument).mockResolvedValue({
      scope: "global",
      markdown: "# Director memory\n\n- Never invent extra performers.\n",
      placeholder: false,
      updated_at: "2026-09-21T00:00:00Z",
    });
    vi.mocked(saveDirectorMemoryDocument).mockResolvedValue({
      scope: "global",
      markdown: "# Director memory\n\n- Never invent extra performers.\n- Keep identities exact.\n",
      placeholder: false,
      updated_at: "2026-09-21T00:00:00Z",
    });
    render(<DirectorMemorySetup soulId="adult-video" />);

    const editor = await screen.findByLabelText("MEMORY.md");
    expect(getDirectorMemoryDocument).toHaveBeenCalledWith("global", null, "adult-video");
    expect((editor as HTMLTextAreaElement).value).toContain("Never invent extra performers.");
    fireEvent.change(editor, {
      target: { value: "# Director memory\n\n- Never invent extra performers.\n- Keep identities exact.\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save MEMORY.md" }));

    await waitFor(() => {
      expect(saveDirectorMemoryDocument).toHaveBeenCalledWith(
        expect.stringContaining("Keep identities exact"),
        "global",
        null,
        "adult-video",
      );
    });
  });
});
