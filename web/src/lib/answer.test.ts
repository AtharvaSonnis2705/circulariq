import { describe, expect, it } from "vitest";

import type { AskEvent } from "./api";
import { applyEvent, toMarkdown } from "./answer";

function build(events: AskEvent[]) {
  return events.reduce(applyEvent, []);
}

describe("answer blocks", () => {
  it("attaches citations to the block they support, before trailing whitespace", () => {
    const blocks = build([
      { type: "text", block: 0, text: "The REF is a fund. " },
      { type: "citation", block: 0, source: 1, cited_text: "1.1 A REF shall be created" },
      { type: "text", block: 1, text: "It is held by the exchange.\n\n" },
      { type: "citation", block: 1, source: 0, cited_text: "..." },
      { type: "citation", block: 1, source: 2, cited_text: "..." },
    ]);
    expect(toMarkdown(blocks)).toBe(
      "The REF is a fund.[2](#src-1) It is held by the exchange.[1](#src-0)[3](#src-2)\n\n",
    );
  });

  it("does not duplicate a source cited twice in one block", () => {
    const blocks = build([
      { type: "citation", block: 0, source: 3, cited_text: "a" },
      { type: "text", block: 0, text: "Rule." },
      { type: "citation", block: 0, source: 3, cited_text: "a" },
    ]);
    expect(blocks[0].sources).toEqual([3]);
    expect(toMarkdown(blocks)).toBe("Rule.[4](#src-3)");
  });

  it("leaves uncited text untouched", () => {
    expect(toMarkdown(build([{ type: "text", block: 0, text: "**Funding**\n\n" }]))).toBe("**Funding**\n\n");
  });
});
