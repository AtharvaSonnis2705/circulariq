"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";

import { Answer } from "@/components/Answer";
import { SourceList } from "@/components/SourceList";
import { type AskEvent, type Source, type Stats, askStream, fetchStats } from "@/lib/api";
import { type AnswerBlock, applyEvent, toMarkdown } from "@/lib/answer";

const EXAMPLES = [
  "How often must a stock broker settle a client's running account?",
  "What is the Recovery Expense Fund for debentures?",
  "Can a debenture trustee outsource its activities?",
  "What is the Credit Risk-o-Meter for debt securities?",
  "What disclosures must a research analyst make?",
];

type Status = "idle" | "searching" | "streaming" | "done" | "error";
type Done = Extract<AskEvent, { type: "done" }>;

export function Chat() {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [sources, setSources] = useState<Source[]>([]);
  const [blocks, setBlocks] = useState<AnswerBlock[]>([]);
  const [done, setDone] = useState<Done | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchStats().then(setStats);
  }, []);

  const markdown = useMemo(() => toMarkdown(blocks), [blocks]);
  const cited = useMemo(() => new Set(blocks.flatMap((b) => b.sources)), [blocks]);
  const quotes = useMemo(() => Object.assign({}, ...blocks.map((b) => b.quotes)), [blocks]);

  async function ask(q: string) {
    const text = q.trim();
    if (text.length < 3 || status === "searching" || status === "streaming") return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setAsked(text);
    setStatus("searching");
    setSources([]);
    setBlocks([]);
    setDone(null);
    setError(null);
    setActive(null);
    const started = performance.now();
    try {
      await askStream(
        text,
        (event) => {
          if (event.type === "sources") setSources(event.sources);
          else if (event.type === "text" || event.type === "citation") {
            setStatus("streaming");
            setBlocks((prev) => applyEvent(prev, event));
          } else if (event.type === "done") {
            setDone({ ...event, timings_ms: { ...event.timings_ms, total: performance.now() - started } });
            setStatus("done");
          } else if (event.type === "error") {
            setError(event.message);
            setStatus("error");
          }
        },
        controller.signal,
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError("Couldn't reach the server. Please try again.");
        setStatus("error");
      }
    }
  }

  function cite(index: number) {
    setActive(index);
    document.getElementById(`source-${index}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  const busy = status === "searching" || status === "streaming";
  const docCount = stats ? Object.values(stats.documents).reduce((a, b) => a + b, 0) : null;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-12">
      <header className="mb-8">
        <div className="flex items-baseline justify-between gap-4">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">CircularIQ</h1>
          <Link href="/evals" className="text-sm text-accent hover:underline">
            How well does it work? →
          </Link>
        </div>
        <p className="mt-1.5 max-w-2xl text-muted">
          Ask about SEBI regulations. Every answer cites the exact paragraph and page of the master
          circular it comes from.
        </p>
        {stats && (
          <p className="mt-2 text-xs text-muted">
            Indexed: {docCount} SEBI documents in force · {stats.pages.toLocaleString("en-IN")} pages ·{" "}
            {stats.chunks.toLocaleString("en-IN")} passages
          </p>
        )}
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
        className="flex flex-col gap-2 sm:flex-row"
      >
        <label htmlFor="question" className="sr-only">
          Your question
        </label>
        <textarea
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              ask(question);
            }
          }}
          rows={2}
          maxLength={500}
          placeholder="e.g. What are the limits on outsourcing for debenture trustees?"
          className="min-h-[52px] flex-1 resize-none rounded-lg border border-border bg-surface px-3.5 py-3 text-[15px] outline-none placeholder:text-muted focus:border-accent"
        />
        <button
          type="submit"
          disabled={busy || question.trim().length < 3}
          className="rounded-lg bg-accent px-5 py-3 text-sm font-medium text-surface disabled:opacity-50"
        >
          {busy ? "Answering…" : "Ask"}
        </button>
      </form>

      {status === "idle" && (
        <div className="mt-4 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setQuestion(ex);
                ask(ex);
              }}
              className="rounded-full border border-border bg-surface px-3 py-1.5 text-left text-sm text-muted hover:border-accent hover:text-foreground"
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      {status !== "idle" && (
        <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section aria-live="polite">
            <p className="mb-3 text-sm font-medium text-muted">{asked}</p>
            {status === "searching" && <p className="text-muted">Searching SEBI documents…</p>}
            {blocks.length > 0 && (
              <Answer
                markdown={markdown}
                sources={sources}
                quotes={quotes}
                streaming={status === "streaming"}
                onCite={cite}
              />
            )}
            {error && <p className="mt-3 rounded-lg bg-highlight px-3 py-2 text-sm">{error}</p>}
            {done?.truncated && (
              <p className="mt-3 text-sm text-muted">The answer was cut short. Try a narrower question.</p>
            )}
            {done?.answered && (
              <p className="mt-5 text-xs text-muted">
                Answered in {(done.timings_ms.total / 1000).toFixed(1)}s · {cited.size} cited of{" "}
                {sources.length} passages · {done.model}
              </p>
            )}
          </section>
          {sources.length > 0 && (status !== "done" || done?.answered) && (
            <aside>
              <h2 className="mb-3 text-sm font-medium text-muted">Sources</h2>
              <SourceList sources={sources} cited={cited} active={active} quotes={quotes} />
            </aside>
          )}
        </div>
      )}

      <footer className="mt-16 border-t border-border pt-4 text-xs leading-5 text-muted">
        Information, not legal advice. Answers are generated by AI from the latest SEBI master circulars
        and circulars published on sebi.gov.in (superseded versions excluded). Always check the linked
        source before relying on it. Built by{" "}
        <a href="https://atharvasonnisportfolio.vercel.app" className="underline">
          Atharva Sonnis
        </a>{" "}
        ·{" "}
        <a href="https://github.com/AtharvaSonnis2705/circulariq" className="underline">
          Source code
        </a>
      </footer>
    </div>
  );
}
