// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChoiceChecklist, parseChoiceQuestionsFromText } from "./ChoiceChecklist";

describe("ChoiceChecklist", () => {
  afterEach(cleanup);

  it("parses markdown checkbox quizzes into questions", () => {
    const questions = parseChoiceQuestionsFromText(
      `- For the “Jenny on knees” image:
  - [ ] Use Jenny’s existing fullbody_threeview from the library.
  - [ ] Use a new pose image you will upload.

- For the bright lighting:
  - [ ] Cool tungsten key with strong fill.
  - [ ] Warm white wraparound.`,
    );
    expect(questions).toHaveLength(2);
    expect(questions[0].prompt).toMatch(/Jenny on knees/i);
    expect(questions[0].options).toHaveLength(2);
    expect(questions[1].options[1]).toMatch(/Warm white/);
  });

  it("sends ticked options as a compact answer", () => {
    const onSubmit = vi.fn();
    render(
      <ChoiceChecklist
        questions={[
          {
            prompt: "Who is this about?",
            options: ["Jenny", "Wendy", "Both"],
            allow_multiple: true,
          },
        ]}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Jenny" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Wendy" }));
    fireEvent.click(screen.getByRole("button", { name: "Send answers" }));
    expect(onSubmit).toHaveBeenCalledWith("Who is this about?: Jenny; Wendy");
  });
});
