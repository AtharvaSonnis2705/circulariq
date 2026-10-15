import type { AskEvent } from "./api";

/** One answer text block from Claude, with the sources that support it. */
export type AnswerBlock = {
  text: string;
  sources: number[]; // indexes into the sources list, in citation order, unique
  quotes: Record<number, string>; // source index → passage text Claude cited
};

export function applyEvent(blocks: AnswerBlock[], event: AskEvent): AnswerBlock[] {
  if (event.type !== "text" && event.type !== "citation") return blocks;
  const next = blocks.slice();
  while (next.length <= event.block) next.push({ text: "", sources: [], quotes: {} });
  const block = { ...next[event.block] };
  if (event.type === "text") {
    block.text += event.text;
  } else if (!block.sources.includes(event.source)) {
    block.sources = [...block.sources, event.source];
    block.quotes = { ...block.quotes, [event.source]: event.cited_text };
  }
  next[event.block] = block;
  return next;
}

/**
 * Join blocks into one markdown string, placing a citation link right after the text each
 * citation supports: `[2](#src-1)`. The renderer turns those links into citation chips.
 * Markers go before trailing whitespace so they stay attached to the sentence.
 */
export function toMarkdown(blocks: AnswerBlock[]): string {
  return blocks
    .map((b) => {
      if (b.sources.length === 0) return b.text;
      const markers = b.sources.map((s) => `[${s + 1}](#src-${s})`).join("");
      const trimmed = b.text.replace(/\s+$/, "");
      return `${trimmed}${markers}${b.text.slice(trimmed.length)}`;
    })
    .join("");
}
