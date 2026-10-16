import type { Metadata } from "next";
import Link from "next/link";

import data from "@/data/evals.json";
import { MODEL_LABELS, VARIANT_LABELS, pct, type EvalResults } from "@/lib/evals";

export const metadata: Metadata = {
  title: "Evals · CircularIQ",
  description: "Measured retrieval recall, answer faithfulness and citation accuracy for CircularIQ.",
};

const REPO = "https://github.com/AtharvaSonnis2705/circulariq";
const results = data as EvalResults;
const USD_INR = 88; // approximate rate, for a readable rupee figure only

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted">
            {head.map((h, i) => (
              <th key={h} className={`px-3 py-2 font-medium ${i ? "text-right" : ""}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={String(r[0])} className="border-b border-border last:border-0">
              {r.map((c, i) => (
                <td key={i} className={`px-3 py-2 ${i ? "text-right tabular-nums" : ""}`}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Section({ title, intro, children }: { title: string; intro?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold">{title}</h2>
      {intro && <p className="mt-1 mb-3 max-w-3xl text-sm text-muted">{intro}</p>}
      {children}
    </section>
  );
}

const runDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

export default function EvalsPage() {
  const { retrieval, answers } = results;
  const sonnet = answers?.by_model["claude-sonnet-5-5"];
  const failures = answers?.rows.filter((r) => !r.passed) ?? [];
  const misses = retrieval?.questions.filter(
    (q) => q.expected_ranks.length && q.expected_ranks.some((r) => r == null || r > 5),
  );

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:py-12">
      <Link href="/" className="text-sm text-accent">
        ← Ask a question
      </Link>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">How well does it work?</h1>
      <p className="mt-1.5 max-w-3xl text-muted">
        Every number on this page comes from scripts in the repo, run against a hand-checked set of{" "}
        {retrieval ? retrieval.counts.answerable + retrieval.counts.unanswerable : "–"} questions about SEBI
        circulars, including questions the documents can&apos;t answer.{" "}
        <a className="underline" href={`${REPO}/tree/main/api/evals`}>
          Questions and scripts
        </a>
        .
      </p>

      <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Tile label="Recall@5" value={pct(retrieval?.headline["recall@5"])} note="right passage in top 5" />
        <Tile label="MRR" value={retrieval ? retrieval.headline.mrr.toFixed(2) : "–"} note="1.0 = always ranked #1" />
        <Tile label="Faithfulness" value={pct(sonnet?.faithfulness)} note="claims supported (Sonnet)" />
        <Tile label="Citation support" value={pct(sonnet?.citation_support)} note="citations that back their claim" />
        <Tile
          label="Correct refusals"
          value={sonnet ? `${sonnet.correct_refusals}/${sonnet.unanswerable}` : "–"}
          note="off-topic / not in corpus"
        />
        <Tile
          label="Cost per answer"
          value={sonnet ? `$${sonnet.cost_per_answer_usd.toFixed(3)}` : "–"}
          note={sonnet ? `Sonnet · ≈ ₹${(sonnet.cost_per_answer_usd * USD_INR).toFixed(2)} at ₹${USD_INR}/$` : undefined}
        />
      </div>

      {retrieval && (
        <>
          <Section
            title="Retrieval: which search setup finds the right passage?"
            intro={`Each question names the passage that answers it. Recall@k is the share of those passages found in the top k results. Every variant searches the same ${retrieval.counts.answerable} answerable questions. The model sees the top ${retrieval.config.context_passages}.`}
          >
            <Table
              head={["Search", "Recall@1", "Recall@5", "Recall@10", "MRR"]}
              rows={Object.entries(retrieval.ablations).map(([name, m]) => [
                VARIANT_LABELS[name] ?? name,
                pct(m["recall@1"]),
                pct(m["recall@5"]),
                pct(m["recall@10"]),
                m.mrr.toFixed(3),
              ])}
            />
            {retrieval.headline["hard_recall@5"] != null && (
              <p className="mt-2 text-xs text-muted">
                On the questions phrased like a real user would ask (no wording copied from the circular), recall@5 is{" "}
                {pct(retrieval.headline["hard_recall@5"])}.
              </p>
            )}
          </Section>

          <Section
            title="The “not found” cutoff"
            intro="If the best passage scores below the cutoff, CircularIQ says it couldn't find an answer instead of calling the model. Too high and it refuses real questions; too low and unanswerable questions reach the model (which is told to refuse them, as a second line of defence)."
          >
            <Table
              head={["Cutoff", "Answerable questions refused", "Unanswerable questions let through"]}
              rows={retrieval.threshold_sweep.map((t) => [
                `${t.threshold.toFixed(2)}${t.production ? " (current)" : ""}`,
                `${t.false_refusals} / ${retrieval.counts.answerable}`,
                `${t.false_answers} / ${retrieval.counts.unanswerable}`,
              ])}
            />
          </Section>
        </>
      )}

      {answers ? (
        <Section
          title="Answers: faithful, cited, complete?"
          intro={`Each answer is graded by ${MODEL_LABELS[answers.judge_model] ?? answers.judge_model} against the exact passages it was given. A question passes when the answer has no unsupported claims and includes every expected fact, or, for unanswerable questions, when it refuses.`}
        >
          <Table
            head={["Model", "Pass rate", "Faithfulness", "Citation support", "Text cited", "Facts present", "False refusals", "Cost / answer", "Median time"]}
            rows={Object.entries(answers.by_model).map(([model, s]) => [
              MODEL_LABELS[model] ?? model,
              pct(s.pass_rate),
              pct(s.faithfulness),
              pct(s.citation_support),
              pct(s.citation_coverage),
              pct(s.facts_present),
              s.false_refusals,
              `$${s.cost_per_answer_usd.toFixed(4)}`,
              s.median_latency_s == null ? "–" : `${s.median_latency_s.toFixed(1)} s`,
            ])}
          />
          {answers.judge_note && (
            <p className="mt-3 rounded-lg bg-highlight px-3 py-2 text-xs leading-5">
              <span className="font-medium">Known issue:</span> {answers.judge_note}
            </p>
          )}
          <h3 className="mt-6 mb-2 text-sm font-medium">Failures ({failures.length})</h3>
          <div className="flex flex-col gap-2">
            {failures.map((r) => (
              <details key={`${r.id}-${r.model}`} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm">
                <summary className="cursor-pointer">
                  <span className="font-mono text-xs text-muted">{r.id}</span> · {MODEL_LABELS[r.model] ?? r.model} ·{" "}
                  {r.question}
                </summary>
                <div className="mt-2 space-y-2 text-muted">
                  {r.explanation && <p>{r.explanation}</p>}
                  {!!r.unsupported_claims?.length && <p>Unsupported: {r.unsupported_claims.join(" · ")}</p>}
                  {!!r.missing_facts?.length && <p>Missing: {r.missing_facts.join(" · ")}</p>}
                  {r.error && <p>Error: {r.error}</p>}
                  {r.answer && <p className="whitespace-pre-wrap rounded bg-background p-2 text-foreground">{r.answer}</p>}
                </div>
              </details>
            ))}
          </div>
        </Section>
      ) : (
        <Section title="Answers" intro="Answer-quality results will appear after the first graded run." >
          {null}
        </Section>
      )}

      {misses && misses.length > 0 && (
        <Section title={`Retrieval misses (${misses.length})`} intro="Questions where an expected passage wasn't in the top 5.">
          <ul className="list-disc pl-5 text-sm text-muted">
            {misses.map((q) => (
              <li key={q.id}>
                <span className="font-mono text-xs">{q.id}</span> {q.question} (ranks:{" "}
                {q.expected_ranks.map((r) => r ?? "not found").join(", ")})
              </li>
            ))}
          </ul>
        </Section>
      )}

      <footer className="mt-16 border-t border-border pt-4 text-xs leading-5 text-muted">
        {retrieval && (
          <p>
            Retrieval run {runDate(retrieval.run_at)} at commit {retrieval.commit}; re-run in CI on every push.
          </p>
        )}
        {answers && (
          <p>
            Answer run {runDate(answers.run_at)} at commit {answers.commit}; cost ${answers.total_cost_usd.toFixed(2)}{" "}
            including grading.
          </p>
        )}
      </footer>
    </main>
  );
}
