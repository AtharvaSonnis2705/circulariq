# CircularIQ

> Ask questions about SEBI regulations and get answers that cite the exact paragraph and page of the master circular they come from.

**[Live demo](https://circulariq.vercel.app)** · **Video:** _coming soon_ · ![CI](https://github.com/AtharvaSonnis2705/circulariq/actions/workflows/ci.yml/badge.svg)

## The problem

SEBI's rules for brokers, mutual funds, depositories and other intermediaries live in master circulars that run to hundreds of pages each. The Master Circular for Mutual Funds alone is 748 pages. Compliance teams answer questions like "how often must a broker settle a client's running account?" by searching PDFs by hand. Generic chatbots answer from stale training data and can't show where an answer came from, which makes them unusable for compliance work.

CircularIQ answers only from the SEBI documents currently in force, and every claim links to the paragraph and PDF page it came from.

## How it works

```
                 ┌───────────── ingestion (offline, idempotent) ─────────────┐
 sebi.gov.in ──▶ │ fetch PDFs ─▶ structure-aware chunking ─▶ voyage-4 embed │ ──▶ Neon Postgres
                 │ (polite,      (chapters, numbered paras,   (1024-d)       │     pgvector + full-text
                 │  resumable)    annexures, page numbers)                   │
                 └───────────────────────────────────────────────────────────┘

 question ─▶ hybrid search (pgvector ∪ full-text, RRF) ─▶ 30 candidates ─▶ Voyage rerank-3 ─▶ top 6
          ─▶ relevance gate (off-topic → "not found", no LLM call)
          ─▶ Claude (passages sent as search_result blocks, citations on) ─▶ streamed via SSE
          ─▶ Next.js UI: answer with citation chips · source cards · "open PDF at page N"
```

- **Structure-aware chunking.** SEBI documents use chapters, numbered paragraphs (`3.1.`, or `11.1.` within Chapter 11) and annexures. Chunks follow those boundaries and never cross a chapter, so a citation reads `Chapter IV › Paras 2.1–3 · p. 54`.
- **Only rules in force.** When a newer master circular on the same topic rescinds an older one, the old version is marked superseded and excluded from answers. It's kept for future "what changed?" queries.
- **Hybrid retrieval.** Keyword search catches exact terms ("Regulation 54", "REF"). Vector search catches paraphrases. Reciprocal rank fusion merges the two without tuning weights, and a cross-encoder reranker picks the final six.
- **API-native citations.** Passages go to Claude as `search_result` content blocks, so citations come back from the API and are tied to real passages. The model can't invent a reference.
- **Guardrails.** A rerank-score cutoff, tuned on the golden set, answers off-topic questions with "not found" before any LLM call. The prompt tells the model to state what the excerpts don't cover instead of guessing.
- **Observability.** Optional Langfuse tracing records each question's retrieval scores and timings, the model that answered, tokens, cost and time to first token. When it is on, the questions people type are stored in Langfuse.
- **Cost-aware model routing.** Sonnet 5.5 writes answers until a daily budget, then Haiku 5.5 takes over. Sonnet calls opt into server-side refusal fallbacks. Per-IP and global rate limits cap spend on the public demo.

## Results

Every number below comes from the scripts in [`api/evals/`](api/evals), run against a hand-checked golden set of **73 questions**: 63 answerable (including 10 phrased like a real user, with no wording copied from the circulars, and 6 that need two passages), plus 10 that should be refused (off-topic, or not covered by SEBI's documents). Full results, including every failure: **[circulariq.vercel.app/evals](https://circulariq.vercel.app/evals)**.

**Retrieval** (63 answerable questions, $0: Voyage + Postgres only, re-run in CI on every push)

| Search | Recall@1 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|
| Keyword only | 19% | 44% | 55% | 0.31 |
| Vector only | 60% | 92% | 97% | 0.76 |
| Hybrid (RRF) | 42% | 71% | 91% | 0.57 |
| **Hybrid + rerank (production)** | **79%** | **100%** | **100%** | **0.91** |

**Answers** (judged by Sonnet 5.5 against the exact passages each answer was given)

| | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|
| Faithfulness (claims supported by the passages) | 95% | 96% |
| Citation support (citations that back their sentence) | 99.8% | 99.4% |
| Expected facts present | 100% | 98% |
| Share of answer text carrying a citation | 58% | 32% |
| Unanswerable questions correctly refused | 10/10 | 10/10 |
| Answerable questions wrongly refused | 0/63 | 0/63 |
| Cost per answer | $0.019 | $0.0012 |

The answer run cost $3.81 including grading. Pass rate and faithfulness are a **lower bound**: in this run the judge wasn't shown the passages' issue dates, so correct mentions of a circular's date counted as unsupported (fixed for the next run). The remaining failures are small overreaches, like an inferred notch count or an unstated trigger level. They're listed on the evals page.

**Other measurements**

| What | Result |
|---|---|
| Corpus | 52 SEBI documents in force (28 master circulars, 24 circulars), 4,922 pages, 4,453 passages |
| Time to first token | Haiku 5.5: 3.4 s · **Sonnet 5.5: 1.0 s** |
| Retrieval latency (deployed, Render Ohio ↔ Neon us-east-2) | ~0.45 s: embed ~130 ms · hybrid search ~50 ms · rerank ~260 ms |
| Ingestion | ~1.9M embedding tokens for the full corpus; unchanged chunks reuse stored vectors on re-ingest |

What the evals changed:
- **The reranker does the heavy lifting.** Hybrid search alone ranks worse than vector search alone (the keyword OR-query adds noise), but it widens the candidate pool and the reranker sorts it: 71% → 100% recall@5.
- **The "not found" cutoff dropped from 0.60 to 0.50.** At 0.60, two real questions were refused. At 0.50, none are, and every off-topic question (top score ≤ 0.46) is still stopped before the model.

Run them yourself: `cd api && uv run python -m evals.run_retrieval` (free) · `uv run python -m evals.run_answers` (~$4).

## Key decisions and trade-offs

- **SEBI only, latest 25 + 25 documents.** SEBI's paginated listing and the RBI website reject automated requests. The downloader uses only pages served to normal visitors and stops on any block page instead of working around it. Master circulars consolidate every older circular on a topic, so 25 of them cover most of the rulebook.
- **Postgres for everything.** pgvector and full-text search sit in one database (Neon free tier), so there's no separate vector store to run or keep in sync, and hybrid search is a single SQL query.
- **Citations instead of JSON output.** Claude's citations feature can't be combined with structured outputs. The citations themselves are the structure the UI needs.
- **Free-tier hosting.** The API runs on Render's free tier, which sleeps when idle. The frontend pings `/health` on load and shows a "waking up" state, so a cold start never looks like a crash.

## Run locally

```bash
# API: needs Neon (Postgres), Voyage and Anthropic keys in api/.env
cd api && cp .env.example .env && uv sync
uv run python -m circulariq.ingest all
uv run uvicorn circulariq.main:app --reload

# Web
cd web && cp .env.example .env.local && pnpm install && pnpm dev
```

Tests: `cd api && uv run pytest` · `cd web && pnpm test`

## Roadmap

- [x] Ingestion, chunking, hybrid retrieval, reranking
- [x] Streaming cited answers, Next.js UI
- [x] Deploy (Render + Vercel)
- [x] Eval suite: golden set, recall@k / MRR with ablations (CI-gated), LLM-judge faithfulness and citation support, public `/evals` page; Langfuse tracing
- [ ] MCP server so Claude Desktop can query CircularIQ
- [ ] "What changed?": compare a new circular with the master circular it amends

## Tech

Python 3.12 · FastAPI · psycopg 3 · Postgres (Neon) + pgvector · Voyage AI (voyage-4, rerank-3) · Claude Sonnet 5.5 / Haiku 5.5 · Langfuse · Next.js 16 · React 19 · Tailwind 4 · Docker · GitHub Actions

_Information, not legal advice. Always check the linked source._
