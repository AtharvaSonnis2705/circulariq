"use client";

import type { Source } from "@/lib/api";

type Props = {
  sources: Source[];
  cited: Set<number>;
  active: number | null;
  quotes: Record<number, string>;
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function SourceList({ sources, cited, active, quotes }: Props) {
  // Cited sources first, in their citation number order; uncited ones after, dimmed.
  const ordered = [...sources].sort(
    (a, b) => Number(cited.has(b.index)) - Number(cited.has(a.index)) || a.index - b.index,
  );
  return (
    <ol className="space-y-2.5">
      {ordered.map((s) => {
        const isCited = cited.has(s.index);
        return (
          <li
            key={s.index}
            id={`source-${s.index}`}
            className={`rounded-lg border p-3 transition-colors ${
              active === s.index ? "border-accent bg-highlight" : "border-border bg-surface"
            } ${isCited ? "" : "opacity-60"}`}
          >
            <div className="flex items-start gap-2.5">
              <span className="mt-0.5 flex h-5 min-w-5 items-center justify-center rounded bg-accent-soft px-1 text-[11px] font-semibold text-accent">
                {s.index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium leading-snug">{s.title}</p>
                <p className="mt-0.5 text-xs text-muted">
                  {s.section} · p. {s.page} · {s.doc_type === "master_circular" ? "Master circular" : "Circular"},{" "}
                  {formatDate(s.issued_on)}
                </p>
                {quotes[s.index] && (
                  <blockquote className="mt-2 line-clamp-4 border-l-2 border-border pl-2 text-xs leading-5 text-muted">
                    {quotes[s.index]}
                  </blockquote>
                )}
                <a
                  href={s.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-block text-xs font-medium text-accent hover:underline"
                >
                  Open PDF at page {s.page} ↗
                </a>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
