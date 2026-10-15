# CircularIQ API

FastAPI service: ingestion pipeline, hybrid retrieval and the streaming `/ask` endpoint.
See the [project README](../README.md) for the architecture and results.

```bash
cp .env.example .env          # Neon, Voyage and Anthropic keys
uv sync
uv run python -m circulariq.ingest all   # fetch SEBI PDFs, embed, load into Postgres
uv run uvicorn circulariq.main:app --reload
uv run pytest -q
```
