// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryPatrolStatus } from "./MemoryPatrolStatus";

vi.mock("./api", () => ({
  getDirectorPatrol: vi.fn(),
}));

import { getDirectorPatrol } from "./api";

describe("MemoryPatrolStatus", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows the interval and open task count", async () => {
    vi.mocked(getDirectorPatrol).mockResolvedValue({
      enabled: true,
      interval_sec: 1800,
      last_run_at: new Date().toISOString(),
      next_at: null,
      projects: { prj_1: { count: 2, soul_id: "studio" } },
    });
    render(<MemoryPatrolStatus projectId="prj_1" />);
    expect(await screen.findByText(/Memory check every 30 min/)).toBeTruthy();
    expect(screen.getByText(/2 open tasks/)).toBeTruthy();
  });
});
