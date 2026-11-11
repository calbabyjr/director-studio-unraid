import { describe, expect, it } from "vitest";
import { NAV_ITEMS } from "./navigation";

describe("NAV_ITEMS", () => {
  it("exposes the three desktop workflow stages in production order", () => {
    expect(NAV_ITEMS).toEqual([
      { id: "director", label: "Director", step: "01", hint: "Plan the story and the shots" },
      { id: "assets", label: "Assets", step: "02", hint: "Cast actors, places, props, and voices" },
      { id: "production", label: "Production", step: "03", hint: "Render the shots" },
    ]);
  });
});
