"""CircularIQ ingestion CLI.

uv run python -m circulariq.ingest fetch [--limit N]   download new SEBI PDFs (polite, resumable)
uv run python -m circulariq.ingest parse [--limit N]   dry run: chunk stats + token estimate, no API calls
uv run python -m circulariq.ingest load  [--force]     embed with Voyage and write to Neon
uv run python -m circulariq.ingest all                 fetch + load
uv run python -m circulariq.ingest stats               what's in the database
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict

from circulariq.config import get_settings
from circulariq.embed import estimate_tokens
from circulariq.ingest.parse import embedding_text, parse_pdf
from circulariq.ingest.sources import BlockedError, fetch_corpus, load_manifest


def cmd_fetch(limit: int | None) -> None:
    data_dir = get_settings().data_dir
    try:
        added = fetch_corpus(data_dir, limit_per_type=limit)
    except BlockedError as e:
        sys.exit(f"Stopped: {e}")
    print(f"Fetched {len(added)} new PDFs. Manifest: {len(load_manifest(data_dir))} documents.")


def cmd_parse(limit: int | None) -> None:
    data_dir = get_settings().data_dir
    out_dir = data_dir / "parsed"
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = list(load_manifest(data_dir).values())[:limit]
    total_chunks = total_tokens = total_pages = 0
    for e in entries:
        parsed = parse_pdf(data_dir / e.pdf_path)
        tokens = sum(estimate_tokens(embedding_text(e.title, c)) for c in parsed.chunks)
        total_chunks += len(parsed.chunks)
        total_tokens += tokens
        total_pages += parsed.page_count
        (out_dir / f"{(data_dir / e.pdf_path).stem}.json").write_text(
            json.dumps(
                {
                    "title": e.title,
                    "ref_no": parsed.ref_no,
                    "page_count": parsed.page_count,
                    "chunks": [asdict(c) for c in parsed.chunks],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        print(
            f"{e.doc_type:15} {parsed.page_count:4}p {len(parsed.chunks):4} chunks  {e.title[:60]}"
        )
    print(
        f"\n{len(entries)} docs · {total_pages} pages · {total_chunks} chunks · "
        f"~{total_tokens:,} tokens to embed (inspect {out_dir}/)"
    )


def cmd_load(limit: int | None, force: bool) -> None:
    from circulariq.db import connect, migrate
    from circulariq.embed import Embedder
    from circulariq.ingest.load import ingest_document

    settings = get_settings()
    # Smallest first: with a rate-limited embedding API, search becomes useful sooner.
    entries = sorted(load_manifest(settings.data_dir).values(), key=lambda e: e.bytes)[:limit]
    embedder = Embedder()
    import psycopg

    conn = connect()
    migrate(conn)
    loaded = 0
    try:
        for e in entries:
            for attempt in range(3):
                try:
                    loaded += ingest_document(conn, e, settings.data_dir, embedder, force=force)
                    break
                except psycopg.OperationalError:
                    # Network blip or Neon compute restart: each document is its own
                    # transaction, so reconnect and redo just this one.
                    if attempt == 2:
                        raise
                    print("    database connection lost; reconnecting")
                    conn.close()
                    time.sleep(5 * (attempt + 1))
                    conn = connect()
        from circulariq.ingest.supersede import mark_superseded

        for old_doc, new_doc in mark_superseded(conn):
            print(f"  superseded: {old_doc}  →  {new_doc}")
    finally:
        conn.close()
    print(
        f"\nLoaded {loaded} documents ({len(entries) - loaded} already up to date). "
        f"Voyage tokens used: {embedder.tokens_used:,}"
    )


def cmd_stats() -> None:
    from circulariq.db import connect

    with connect() as conn:
        rows = conn.execute(
            "SELECT d.doc_type, count(DISTINCT d.id), count(c.id) "
            "FROM documents d LEFT JOIN chunks c ON c.document_id = d.id GROUP BY d.doc_type"
        ).fetchall()
    for doc_type, docs, chunks in rows:
        print(f"{doc_type:15} {docs:4} docs {chunks:6} chunks")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m circulariq.ingest",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "parse", "load", "all"):
        p = sub.add_parser(name)
        p.add_argument(
            "--limit", type=int, default=None, help="max documents (per listing for fetch)"
        )
        if name in ("load", "all"):
            p.add_argument(
                "--force", action="store_true", help="re-parse and re-load unchanged docs"
            )
    sub.add_parser("stats")
    args = parser.parse_args()

    if args.cmd == "fetch":
        cmd_fetch(args.limit)
    elif args.cmd == "parse":
        cmd_parse(args.limit)
    elif args.cmd == "load":
        cmd_load(args.limit, args.force)
    elif args.cmd == "all":
        cmd_fetch(args.limit)
        cmd_load(None, args.force)
    elif args.cmd == "stats":
        cmd_stats()


if __name__ == "__main__":
    main()
