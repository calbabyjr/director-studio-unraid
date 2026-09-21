// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryNotes } from "./MemoryNotes";
import { addDirectorMemoryNote, deleteDirectorMemoryNote, getDirectorMemory } from "./api";

vi.mock("./api", () => ({
  getDirectorMemory: vi.fn(),
  addDirectorMemoryNote: vi.fn(),
  deleteDirectorMemoryNote: vi.fn(),
}));

describe("MemoryNotes", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("lists standing notes and can remember and forget them", async () => {
    vi.mocked(getDirectorMemory).mockResolvedValue([
      {
        id: "mem_dungeon",
        text: "This production is a dungeon, never a warehouse.",
        scope: "project",
        source: "auto",
        created_at: "2026-09-21T00:00:00Z",
        updated_at: "2026-09-21T00:00:00Z",
      },
    ]);
    vi.mocked(addDirectorMemoryNote).mockResolvedValue({
      id: "mem_actors",
      text: "Do not create new actors unless asked.",
      scope: "global",
      source: "user",
      created_at: "2026-09-21T00:00:00Z",
      updated_at: "2026-09-21T00:00:00Z",
    });
    render(<MemoryNotes projectId="prj_1" />);

    expect(await screen.findByText("This production is a dungeon, never a warehouse.")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("Remember: never create actors unless asked"), {
      target: { value: "Do not create new actors unless asked." },
    });
    fireEvent.change(screen.getByLabelText("Note scope"), { target: { value: "global" } });
    fireEvent.click(screen.getByRole("button", { name: "Remember" }));

    await waitFor(() => {
      expect(addDirectorMemoryNote).toHaveBeenCalledWith(
        "prj_1",
        "Do not create new actors unless asked.",
        "global",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Forget" }));
    await waitFor(() => {
      expect(deleteDirectorMemoryNote).toHaveBeenCalledWith("prj_1", "mem_dungeon");
    });
  });
});
