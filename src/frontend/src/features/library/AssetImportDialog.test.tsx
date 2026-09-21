// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssetImportDialog } from "./AssetImportDialog";
import { importExternalAsset } from "./api";

vi.mock("./api", () => ({
  importExternalAsset: vi.fn(),
}));

describe("AssetImportDialog", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("keeps a chosen costume image until Import is clicked", async () => {
    vi.mocked(importExternalAsset).mockResolvedValue({} as never);
    const onImported = vi.fn();
    const image = new File(["jpg"], "wardrobe.jpg", { type: "image/jpeg" });
    render(
      <AssetImportDialog
        kind="costumes"
        projectId="prj_1"
        onClose={vi.fn()}
        onImported={onImported}
      />,
    );

    expect(screen.getByRole("button", { name: "Import costume" })).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText("Image file"), { target: { files: [image] } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Red coat" } });

    expect(importExternalAsset).not.toHaveBeenCalled();
    expect(screen.getByText("wardrobe.jpg")).toBeTruthy();
    const importButton = screen.getByRole("button", { name: "Import costume" });
    expect(importButton).toHaveProperty("disabled", false);
    fireEvent.click(importButton);

    await waitFor(() => expect(importExternalAsset).toHaveBeenCalledWith({
      file: image,
      kind: "costumes",
      name: "Red coat",
      notes: undefined,
      projectId: "prj_1",
    }));
    expect(onImported).toHaveBeenCalledTimes(1);
  });

  it("does not import a voice until a name and file are both ready", async () => {
    vi.mocked(importExternalAsset).mockResolvedValue({} as never);
    const audio = new File(["voice"], "mia.wav", { type: "audio/wav" });
    render(
      <AssetImportDialog
        kind="voices"
        projectId="prj_1"
        onClose={vi.fn()}
        onImported={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Audio file"), { target: { files: [audio] } });
    expect(screen.getByRole("button", { name: "Import voice" })).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Mia" } });
    fireEvent.click(screen.getByRole("button", { name: "Import voice" }));

    await waitFor(() => expect(importExternalAsset).toHaveBeenCalledTimes(1));
  });
});
