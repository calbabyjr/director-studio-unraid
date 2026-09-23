import { readFileSync } from "node:fs";
import postcss from "postcss";
import { describe, expect, it } from "vitest";

const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

function resolvedGlobalProperty(selector, property) {
  let value;
  postcss.parse(styles).walkRules((rule) => {
    if (!rule.selectors.includes(selector)) return;
    rule.walkDecls(property, (declaration) => {
      value = declaration.value;
    });
  });
  return value;
}

describe("Director desktop fill", () => {
  it("stretches the split workspace so the canvas does not show below the panels", () => {
    expect(
      resolvedGlobalProperty(".director-chat-layout.director-fill-viewport", "flex"),
    ).toBe("1 1 0");
    expect(
      resolvedGlobalProperty(".director-resizable-workspace", "grid-template-rows"),
    ).toBe("minmax(0, 1fr)");
    expect(
      resolvedGlobalProperty(".director-resizable-workspace .resizable-pane", "height"),
    ).toBe("100%");
    expect(
      resolvedGlobalProperty(".director-resizable-workspace .panel", "flex"),
    ).toBe("1 1 0");
    expect(
      resolvedGlobalProperty(".director-resizable-workspace .panel", "max-height"),
    ).toBe("none");
    expect(
      resolvedGlobalProperty(".director-chat-thread", "flex"),
    ).toBe("1 1 0");
    expect(
      resolvedGlobalProperty(".director-chat-thread .chat-log", "flex"),
    ).toBe("1 1 0");
    expect(
      resolvedGlobalProperty(".director-chat-thread .chat-log", "min-height"),
    ).toBe("0");
  });
});
