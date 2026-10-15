-- CircularIQ schema. Idempotent: safe to run on every deploy/ingest.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL DEFAULT 'sebi',
    doc_type    TEXT NOT NULL CHECK (doc_type IN ('master_circular', 'circular')),
    title       TEXT NOT NULL,
    ref_no      TEXT,
    issued_on   DATE NOT NULL,
    page_url    TEXT NOT NULL UNIQUE,
    pdf_url     TEXT NOT NULL,
    pdf_sha256  TEXT NOT NULL,
    page_count  INT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id             BIGSERIAL PRIMARY KEY,
    document_id    BIGINT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_index    INT NOT NULL,
    section        TEXT NOT NULL,          -- e.g. "Chapter III › Paras 3.1–3.4"
    chapter        TEXT,                   -- e.g. "Chapter III: Security and Covenant Monitoring System"
    heading        TEXT,                   -- paragraph title, when the document has one
    paras          TEXT[] NOT NULL DEFAULT '{}',
    page_start     INT NOT NULL,
    page_end       INT NOT NULL,
    content        TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,          -- of the embedded text; lets re-ingests reuse embeddings
    embedding      vector(1024) NOT NULL,
    -- Full-text side of hybrid search. Headings weigh more than body text.
    tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(heading, '') || ' ' || coalesce(chapter, '')), 'A')
        || setweight(to_tsvector('english', content), 'B')
    ) STORED,
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_content_sha ON chunks (content_sha256);
