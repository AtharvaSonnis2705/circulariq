"""Read and write eval results.

`results/latest.json` holds the newest `retrieval` and `answers` sections side by side; each
script replaces only its own section. Every write also keeps a dated snapshot
(`results/<date>-<commit>.json`) so numbers in the README can be traced to a run. The web
`/evals` page reads a copy of latest.json at build time.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from evals.common import RESULTS_DIR

LATEST = RESULTS_DIR / "latest.json"
WEB_COPY = Path(__file__).resolve().parents[2] / "web" / "src" / "data" / "evals.json"


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_latest() -> dict:
    return json.loads(LATEST.read_text()) if LATEST.exists() else {}


def save_section(name: str, section: dict) -> Path:
    now = datetime.now(UTC)
    commit = git_commit()
    section = {"run_at": now.isoformat(timespec="seconds"), "commit": commit, **section}
    latest = load_latest()
    latest[name] = section
    text = json.dumps(latest, indent=2, ensure_ascii=False) + "\n"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(text)
    snapshot = RESULTS_DIR / f"{now:%Y-%m-%d}-{commit}-{name}.json"
    snapshot.write_text(json.dumps(section, indent=2, ensure_ascii=False) + "\n")
    if WEB_COPY.parent.parent.exists():
        WEB_COPY.parent.mkdir(parents=True, exist_ok=True)
        WEB_COPY.write_text(text)
    print(f"wrote {LATEST.name}, {snapshot.name}")
    return snapshot
