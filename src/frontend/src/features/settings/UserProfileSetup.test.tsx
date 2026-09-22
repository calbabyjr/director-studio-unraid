// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UserProfileSetup } from "./UserProfileSetup";

vi.mock("../director/api", () => ({
  listWorkspaceFiles: vi.fn(),
  saveWorkspaceFile: vi.fn(),
}));

import { listWorkspaceFiles, saveWorkspaceFile } from "../director/api";

const userFile = {
  name: "user.md",
  scope: "global" as const,
  markdown: "# User\n\nCall me Cal.\n",
  reserved: true,
  placeholder: false,
  updated_at: "2026-09-21T00:00:00Z",
};

describe("UserProfileSetup", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("loads user.md and saves edits", async () => {
    vi.mocked(listWorkspaceFiles).mockResolvedValue([userFile]);
    vi.mocked(saveWorkspaceFile).mockResolvedValue({
      ...userFile,
      markdown: "# User\n\nCall me Cal.\nNever invent extras.\n",
    });
    render(<UserProfileSetup />);

    const editor = await screen.findByLabelText("user.md");
    expect((editor as HTMLTextAreaElement).value).toContain("Call me Cal.");
    fireEvent.change(editor, {
      target: { value: "# User\n\nCall me Cal.\nNever invent extras.\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save user.md" }));

    await waitFor(() => {
      expect(saveWorkspaceFile).toHaveBeenCalledWith(
        "user.md",
        expect.stringContaining("Never invent extras"),
        "global",
      );
    });
  });
});
