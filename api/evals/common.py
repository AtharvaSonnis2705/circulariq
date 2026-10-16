"""Shared helpers for the eval scripts: load the golden set, match retrieved chunks to it.

A golden question names the passages that answer it as (document, evidence quote) pairs rather
than chunk ids, so the set survives re-chunking. A retrieved chunk counts as relevant when it
comes from that document and contains the quote (case, whitespace and quote style ignored).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

EVALS_DIR = Path(__file__).parent
GOLDEN_PATH = EVALS_DIR / "golden.jsonl"
RESULTS_DIR = EVALS_DIR / "results"

ANSWERABLE_TYPES = {"factual", "multi-hop"}

_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip().lower()


@dataclass
class Expected:
    doc: str
    evidence: str


@dataclass
class GoldenQuestion:
    id: str
    type: str
    question: str
    expected: list[Expected]
    must_include: list[str] = field(default_factory=list)
    # Phrased the way a real user would ask, without the circular's own wording.
    hard: bool = False

    @property
    def answerable(self) -> bool:
        return self.type in ANSWERABLE_TYPES


def load_golden(path: Path = GOLDEN_PATH) -> list[GoldenQuestion]:
    questions = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        questions.append(
            GoldenQuestion(
                id=raw["id"],
                type=raw["type"],
                question=raw["question"],
                expected=[Expected(**e) for e in raw["expected"]],
                must_include=raw.get("must_include", []),
                hard=raw.get("hard", False),
            )
        )
    return questions


def matches(expected: Expected, title: str, content: str) -> bool:
    return normalize(expected.doc) in normalize(title) and normalize(
        expected.evidence
    ) in normalize(content)
