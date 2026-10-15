"use client";

import ReactMarkdown from "react-markdown";

import type { Source } from "@/lib/api";

type Props = {
  markdown: string;
  sources: Source[];
  quotes: Record<number, string>;
  streaming: boolean;
  onCite: (sourceIndex: number) => void;
};

/** Renders the streamed answer. Links shaped `#src-N` become citation chips. */
export function Answer({ markdown, sources, quotes, streaming, onCite }: Props) {
  return (
    <div className="answer text-[15px] leading-7">
      <ReactMarkdown
        components={{
          a({ href, children }) {
            const match = href?.match(/^#src-(\d+)$/);
            if (!match) {
              return (
                <a href={href} target="_blank" rel="noreferrer" className="text-accent underline">
                  {children}
                </a>
              );
            }
            const index = Number(match[1]);
            const source = sources[index];
            const quote = quotes[index];
            return (
              <button
                type="button"
                onClick={() => onCite(index)}
                title={
                  source
                    ? `${source.title} — ${source.section}, p. ${source.page}${quote ? `\n\n“${quote.slice(0, 300)}${quote.length > 300 ? "…" : ""}”` : ""}`
                    : undefined
                }
                aria-label={`Source ${index + 1}`}
                className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-1 items-center justify-center rounded bg-accent-soft px-1 align-baseline text-[11px] font-semibold text-accent hover:bg-accent hover:text-surface"
              >
                {index + 1}
              </button>
            );
          },
        }}
      >
        {markdown}
      </ReactMarkdown>
      {streaming && (
        <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-accent align-middle" />
      )}
    </div>
  );
}
