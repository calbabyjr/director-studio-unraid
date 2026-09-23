import { useMemo, useState } from "react";

export type ChoiceQuestion = {
  prompt: string;
  options: string[];
  allow_multiple?: boolean;
};

const OPTION_LINE = /^(?:[-*]\s*)?(?:\[[ xX]?\]\s*|[A-Da-d]\)\s+)(.+)$/;

export function parseChoiceQuestionsFromText(content: string): ChoiceQuestion[] {
  const questions: ChoiceQuestion[] = [];
  let prompt = "";
  let options: string[] = [];
  const flush = () => {
    const heading = prompt.replace(/^\d+[.)]\s*/, "").replace(/:\s*$/, "").trim();
    const unique = options.map((item) => item.trim()).filter(Boolean);
    if (heading && unique.length >= 2) {
      questions.push({
        prompt: heading.slice(0, 400),
        options: unique.slice(0, 8),
        allow_multiple: true,
      });
    }
    prompt = "";
    options = [];
  };
  for (const raw of (content || "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) {
      flush();
      continue;
    }
    const option = line.match(OPTION_LINE);
    if (option) {
      const text = option[1].trim();
      if (text && !options.includes(text)) options.push(text);
      continue;
    }
    if (options.length >= 2) flush();
    prompt = line;
  }
  flush();
  return questions.slice(0, 4);
}

export function formatChoiceAnswers(
  questions: ChoiceQuestion[],
  selected: string[][],
  extra = "",
): string {
  const lines: string[] = [];
  questions.forEach((question, index) => {
    const picks = (selected[index] || []).map((item) => item.trim()).filter(Boolean);
    if (!picks.length) return;
    lines.push(`${question.prompt}: ${picks.join("; ")}`);
  });
  const also = extra.trim();
  if (also) lines.push(`Also: ${also}`);
  return lines.join("\n").trim();
}

export function ChoiceChecklist({
  questions,
  disabled,
  onSubmit,
}: {
  questions: ChoiceQuestion[];
  disabled?: boolean;
  onSubmit: (text: string) => void;
}) {
  const [selected, setSelected] = useState<string[][]>(() => questions.map(() => []));
  const [extra, setExtra] = useState("");

  const answer = useMemo(
    () => formatChoiceAnswers(questions, selected, extra),
    [questions, selected, extra],
  );

  const toggle = (questionIndex: number, option: string, allowMultiple: boolean) => {
    setSelected((current) =>
      current.map((picks, index) => {
        if (index !== questionIndex) return picks;
        if (!allowMultiple) return picks.includes(option) ? [] : [option];
        return picks.includes(option) ? picks.filter((item) => item !== option) : [...picks, option];
      }),
    );
  };

  if (!questions.length) return null;

  return (
    <form
      className="choice-checklist"
      onSubmit={(event) => {
        event.preventDefault();
        if (!answer || disabled) return;
        onSubmit(answer);
      }}
    >
      {questions.map((question, questionIndex) => (
        <fieldset key={`${question.prompt}-${questionIndex}`} className="choice-checklist-set" disabled={disabled}>
          <legend>{question.prompt}</legend>
          {question.options.map((option, optionIndex) => {
            const checked = (selected[questionIndex] || []).includes(option);
            const id = `choice-${questionIndex}-${optionIndex}`;
            return (
              <label key={`${optionIndex}-${option}`} className="choice-checklist-option" htmlFor={id}>
                <input
                  id={id}
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggle(questionIndex, option, question.allow_multiple !== false)}
                />
                <span>{option}</span>
              </label>
            );
          })}
        </fieldset>
      ))}
      <label className="choice-checklist-extra">
        <span className="muted tiny">Anything else</span>
        <textarea
          value={extra}
          disabled={disabled}
          rows={2}
          aria-label="Anything else"
          placeholder="Optional extra detail"
          onChange={(event) => setExtra(event.target.value)}
        />
      </label>
      <button type="submit" className="btn primary sm" disabled={disabled || !answer}>
        Send answers
      </button>
    </form>
  );
}
