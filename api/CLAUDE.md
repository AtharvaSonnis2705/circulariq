# Project conventions (Python service)

## Stack
- Python 3.12, managed with **uv** (`uv add`, `uv run`). Never use pip directly.
- FastAPI + Pydantic v2. Settings live in `src/circulariq/config.py` (pydantic-settings); never read `os.environ` elsewhere.
- Claude via the official `anthropic` SDK only. Get the client from `circulariq.llm.get_client()`.
  - `settings.model_fast` (Haiku 5.5) is the default. Use `settings.model_smart` (Sonnet 5.5) only where quality demonstrably needs it, and say why in a comment.
  - Prefer structured outputs over parsing free text. Use prompt caching for long, stable system prompts.

## Layout
- `src/circulariq/` holds application code: `main.py` (FastAPI app + routes), `config.py`, `llm.py`. Add routers under `src/circulariq/routers/` once there are more than ~3 routes.
- `tests/` holds pytest tests. Every new endpoint or pipeline step gets a test in the same change.
- `evals/` (when the project has an AI feature) holds eval datasets and scripts. Eval numbers in the README must come from these scripts.

## Commands
- `uv run uvicorn circulariq.main:app --reload`: dev server on :8000
- `uv run pytest -q`: tests
- `uv run ruff check . && uv run ruff format .`: lint + format

## Rules
- Keep secrets in `.env` (git-ignored). Add every new variable to `.env.example`.
- Type-hint all functions. No bare `except:`.
- Hosting is Render's free tier: keep startup fast, no background threads that assume the server stays up, keep `/health` cheap.
- Cost guardrails: rate-limit public endpoints and cap `max_tokens` on user-triggered calls.

## CircularIQ specifics
- Corpus: SEBI master circulars + circulars, downloaded by `python -m circulariq.ingest fetch`. Only use pages SEBI serves to normal visitors. If a block page appears, stop (`BlockedError`); never work around it.
- Pipeline: `fetch` → `parse` (dry run, no API calls) → `load` (Voyage embed + Neon upsert). All steps are idempotent and resumable.
- Chunks never cross a chapter or annexure, and they carry `section`, `paras` and `page_start`/`page_end` so answers can cite "Chapter III › Para 3.2, p. 36".
- Schema lives in `sql/*.sql` (idempotent, applied by `circulariq.db.migrate`). Embeddings are `voyage-4` at 1024 dims.
