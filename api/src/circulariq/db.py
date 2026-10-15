import re
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from circulariq.config import get_settings

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
_CREDENTIALS = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")


def redact(text: str) -> str:
    """Hide the password in any connection string inside `text` (driver errors can echo it)."""
    return _CREDENTIALS.sub(r"\1***@", text)


def connect() -> psycopg.Connection:
    """Open a connection to Neon with pgvector types registered."""
    url = get_settings().database_url.strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Add your Neon connection string to .env")
    if not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError(
            "DATABASE_URL must start with postgresql:// (copy it from Neon → Connect, "
            "without the leading `psql` or quotes)"
        )
    try:
        # Autocommit: each `with conn.transaction()` block commits on its own, so a long ingest
        # keeps its progress if it crashes halfway, and readers see documents as they land.
        conn = psycopg.connect(url, autocommit=True)
    except psycopg.Error as e:
        # `from None` drops the original exception, whose message may contain the password.
        raise RuntimeError(f"Could not connect to the database: {redact(str(e))}") from None
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        # Fresh database without the extension yet; migrate() creates it and registers.
        conn.rollback()
    return conn


def migrate(conn: psycopg.Connection) -> None:
    """Apply every `sql/*.sql` file in order. Files must be idempotent."""
    for path in sorted(SQL_DIR.glob("*.sql")):
        conn.execute(path.read_text())
    conn.commit()
    register_vector(conn)
