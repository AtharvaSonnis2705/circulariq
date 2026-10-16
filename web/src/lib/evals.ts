// Shape of api/evals/results/latest.json (copied to src/data/evals.json by the eval scripts).
// Either section may be missing until its script has run once.

export type RetrievalMetrics = {
  "recall@1": number;
  "recall@5": number;
  "recall@10": number;
  mrr: number;
};

export type RetrievalQuestion = {
  id: string;
  type: string;
  hard?: boolean;
  question: string;
  expected_ranks: (number | null)[];
  top_score: number;
  passes_gate: boolean;
  top_hits: { title: string; section: string; page: number; score: number }[];
};

export type RetrievalResults = {
  run_at: string;
  commit: string;
  config: { candidates: number; context_passages: number; min_relevance: number; rerank_model: string; embed_model: string };
  counts: { answerable: number; unanswerable: number };
  headline: RetrievalMetrics & {
    "hard_recall@5"?: number | null;
    false_refusals: number;
    false_answers: number;
    [key: string]: number | null | undefined;
  };
  ablations: Record<string, RetrievalMetrics>;
  threshold_sweep: { threshold: number; false_refusals: number; false_answers: number; production: boolean }[];
  questions: RetrievalQuestion[];
};

export type ModelSummary = {
  pass_rate: number | null;
  answerable_pass_rate: number | null;
  faithfulness: number | null;
  citation_support: number | null;
  citation_coverage: number | null;
  facts_present: number | null;
  cited_expected_passage: number | null;
  false_refusals: number;
  correct_refusals: number;
  unanswerable: number;
  answer_cost_usd: number;
  judge_cost_usd: number;
  cost_per_answer_usd: number;
  median_latency_s: number | null;
  errors: number;
};

export type AnswerRow = {
  id: string;
  question: string;
  type: string;
  answerable: boolean;
  model: string;
  status: string;
  passed: boolean;
  refused?: boolean;
  answer?: string;
  explanation?: string;
  unsupported_claims?: string[];
  missing_facts?: string[];
  error?: string;
};

export type AnswerResults = {
  run_at: string;
  commit: string;
  judge_model: string;
  questions: number;
  by_model: Record<string, ModelSummary>;
  rows: AnswerRow[];
  total_cost_usd: number;
  judge_note?: string;
};

export type EvalResults = { retrieval?: RetrievalResults; answers?: AnswerResults };

export const pct = (v: number | null | undefined, digits = 0) =>
  v == null ? "–" : `${(v * 100).toFixed(digits)}%`;

export const MODEL_LABELS: Record<string, string> = {
  "claude-sonnet-5-5": "Sonnet 5.5",
  "claude-haiku-5-5": "Haiku 5.5",
};

export const VARIANT_LABELS: Record<string, string> = {
  keyword: "Keyword only",
  vector: "Vector only",
  hybrid: "Hybrid (RRF)",
  "keyword+rerank": "Keyword + rerank",
  "vector+rerank": "Vector + rerank",
  "hybrid+rerank": "Hybrid + rerank (production)",
};
