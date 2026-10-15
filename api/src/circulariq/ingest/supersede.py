"""Mark master circulars that a newer master circular on the same topic has rescinded.

Each SEBI master circular states that it rescinds the previous master circular on its subject, so
for documents of the same topic we treat the latest one as in force.
"""

from __future__ import annotations

import re
from collections import defaultdict

import psycopg


def topic_key(title: str) -> str:
    """'Master Circular for Debenture Trustees (DTs)' → 'master circular for debenture trustees'"""
    title = re.sub(r"\([^)]*\)", " ", title.lower())
    return re.sub(r"[^a-z0-9]+", " ", title).strip()


def mark_superseded(conn: psycopg.Connection) -> list[tuple[str, str]]:
    """Recompute `documents.superseded_by`. Returns (old title, superseded-by title) pairs."""
    rows = conn.execute(
        "SELECT id, title, issued_on FROM documents WHERE doc_type = 'master_circular'"
    ).fetchall()
    groups: dict[str, list[tuple[int, str, object]]] = defaultdict(list)
    for row in rows:
        groups[topic_key(row[1])].append(row)

    updates: list[tuple[int | None, int]] = []
    pairs: list[tuple[str, str]] = []
    for docs in groups.values():
        docs.sort(key=lambda r: (r[2], r[0]), reverse=True)
        latest = docs[0]
        updates.append((None, latest[0]))
        for old in docs[1:]:
            updates.append((latest[0], old[0]))
            pairs.append((f"{old[1]} ({old[2]})", f"{latest[1]} ({latest[2]})"))
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany("UPDATE documents SET superseded_by = %s WHERE id = %s", updates)
    return pairs
