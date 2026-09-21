// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DirectorSetupPage } from "./DirectorSetupPage";

vi.mock("./DirectorSoulSetup", () => ({
  DirectorSoulSetup: () => <div>Director souls editor</div>,
}));

describe("DirectorSetupPage", () => {
  afterEach(cleanup);

  it("is a standalone setup screen with a close action", () => {
    const onClose = vi.fn();
    render(<DirectorSetupPage onClose={onClose} />);

    expect(screen.getByRole("heading", { name: "Director setup" })).toBeTruthy();
    expect(screen.getByText(/You do not need a project open/)).toBeTruthy();
    expect(screen.getByText("Director souls editor")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close Director setup" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
