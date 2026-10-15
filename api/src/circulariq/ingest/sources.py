"""Polite downloader for public SEBI circulars and master circulars.

Only uses pages SEBI serves to normal visitors (the first page of each listing, each circular's
detail page, and its PDF). SEBI's paginated listing endpoint rejects automated requests, so we
deliberately don't use it. If SEBI ever serves a block page, we stop instead of retrying.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
import pymupdf
from bs4 import BeautifulSoup

LISTINGS: dict[str, str] = {
    "master_circular": "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=6&smid=0",
    "circular": "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0",
}

USER_AGENT = "Mozilla/5.0 (compatible; CircularIQ/0.1; +https://github.com/AtharvaSonnis2705)"
BLOCK_MARKERS = ("Unauthorized Request Blocked", "Unauthorised Access", "Unauthorized Activity")
SEBI_PDF = re.compile(r"^https?://(?:www\.)?sebi\.gov\.in/sebi_data/.+\.pdf$", re.I)
# A "master circular" PDF this short is a cover letter whose chapters are separate linked PDFs.
COVER_LETTER_MAX_PAGES = 10
MAX_PARTS = 25


class BlockedError(RuntimeError):
    """The site served a block page. Stop; never try to work around it."""


@dataclass(frozen=True)
class ListingItem:
    doc_type: str
    title: str
    issued_on: date
    page_url: str


@dataclass
class ManifestEntry:
    doc_type: str
    title: str
    issued_on: str  # ISO date
    page_url: str
    pdf_url: str
    pdf_path: str  # relative to data_dir
    sha256: str
    bytes: int


def parse_listing(
    html: str, doc_type: str, base_url: str = "https://www.sebi.gov.in/"
) -> list[ListingItem]:
    """Parse the Date/Title table on a SEBI listing page."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[ListingItem] = []
    for row in soup.select("table#sample_1 tbody tr"):
        cells = row.find_all("td")
        link = row.find("a", href=True)
        if len(cells) < 2 or link is None:
            continue
        try:
            issued = datetime.strptime(cells[0].get_text(strip=True), "%b %d, %Y").date()
        except ValueError:
            continue
        title = (link.get("title") or link.get_text()).strip()
        items.append(ListingItem(doc_type, title, issued, urljoin(base_url, link["href"])))
    return items


def parse_pdf_url(html: str, page_url: str) -> str | None:
    """Find the PDF behind a circular's detail page (embedded via an iframe viewer)."""
    soup = BeautifulSoup(html, "html.parser")
    for iframe in soup.find_all("iframe", src=True):
        query = parse_qs(urlparse(iframe["src"]).query)
        if file_urls := query.get("file"):
            return urljoin(page_url, file_urls[0])
    for a in soup.find_all("a", href=True):
        if a["href"].lower().endswith(".pdf"):
            return urljoin(page_url, a["href"])
    return None


def slugify(page_url: str) -> str:
    """`.../master-circular-for-debenture-trustees_104743.html` → `master-circular-for-debenture-trustees_104743`"""
    stem = Path(urlparse(page_url).path).stem
    return re.sub(r"[^a-z0-9_\-]+", "-", stem.lower())[:120]


class PoliteClient:
    """httpx client with a fixed delay between requests and a hard stop on block pages."""

    def __init__(self, delay_s: float = 2.0, timeout_s: float = 60.0) -> None:
        self._delay_s = delay_s
        self._last_request = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=timeout_s, follow_redirects=True
        )

    def get(self, url: str) -> httpx.Response:
        wait = self._delay_s - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(3):
            try:
                response = self._client.get(url)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))
                continue
            finally:
                self._last_request = time.monotonic()
            if response.status_code >= 500 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            break
        is_html = "html" in response.headers.get("content-type", "")
        if response.status_code in (401, 403) or (
            is_html and any(m in response.text for m in BLOCK_MARKERS)
        ):
            raise BlockedError(f"{url} returned a block page; stopping.")
        response.raise_for_status()
        return response

    def close(self) -> None:
        self._client.close()


def load_manifest(data_dir: Path) -> dict[str, ManifestEntry]:
    path = data_dir / "manifest.jsonl"
    if not path.exists():
        return {}
    entries = (ManifestEntry(**json.loads(line)) for line in path.read_text().splitlines() if line)
    return {e.page_url: e for e in entries}


def find_linked_parts(pdf: bytes) -> list[tuple[str, str]]:
    """(title, url) of chapter PDFs linked from a short cover-letter master circular.

    Long documents also link to other circulars as references; those are not parts, so we only
    look inside cover letters.
    """
    parts: dict[str, str] = {}
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        if doc.page_count > COVER_LETTER_MAX_PAGES:
            return []
        for page in doc:
            for link in page.get_links():
                uri = (link.get("uri") or "").strip()
                if not SEBI_PDF.match(uri) or uri in parts:
                    continue
                label = re.sub(r"\s+", " ", page.get_textbox(link["from"])).strip()
                parts[uri] = label or _title_from_filename(uri)
    return [(title, url) for url, title in list(parts.items())[:MAX_PARTS]]


def _title_from_filename(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).stem
    name = re.sub(r"^RE_|_p$|_\d+_p$|\bFINAL\b|\bNEW\b", "", name, flags=re.I)
    return re.sub(r"[\s_\-]+", " ", name).strip(" -")


def fetch_corpus(
    data_dir: Path, limit_per_type: int | None = None, log: Callable[[str], None] = print
) -> list[ManifestEntry]:
    """Download new PDFs into `data_dir/raw/<doc_type>/` and append them to the manifest."""
    manifest = load_manifest(data_dir)
    manifest_path = data_dir / "manifest.jsonl"
    data_dir.mkdir(parents=True, exist_ok=True)
    client = PoliteClient()
    added: list[ManifestEntry] = []

    def have(page_url: str) -> bool:
        return page_url in manifest and (data_dir / manifest[page_url].pdf_path).exists()

    def save(
        doc_type: str, title: str, issued_on: date, page_url: str, pdf_url: str, pdf: bytes
    ) -> None:
        rel_path = Path("raw") / doc_type / f"{slugify(page_url)}.pdf"
        (data_dir / rel_path).parent.mkdir(parents=True, exist_ok=True)
        (data_dir / rel_path).write_bytes(pdf)
        entry = ManifestEntry(
            doc_type=doc_type,
            title=title,
            issued_on=issued_on.isoformat(),
            page_url=page_url,
            pdf_url=pdf_url,
            pdf_path=str(rel_path),
            sha256=hashlib.sha256(pdf).hexdigest(),
            bytes=len(pdf),
        )
        with manifest_path.open("a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")
        manifest[page_url] = entry
        added.append(entry)
        log(f"  + {issued_on} {title[:80]} ({len(pdf) // 1024} KB)")

    try:
        for doc_type, listing_url in LISTINGS.items():
            items = parse_listing(client.get(listing_url).text, doc_type)
            log(f"{doc_type}: {len(items)} listed")
            for item in items[:limit_per_type]:
                if have(item.page_url):
                    pdf = (data_dir / manifest[item.page_url].pdf_path).read_bytes()
                else:
                    pdf_url = parse_pdf_url(client.get(item.page_url).text, item.page_url)
                    if pdf_url is None:
                        log(f"  skip (no PDF): {item.title}")
                        continue
                    pdf = client.get(pdf_url).content
                    if not pdf.startswith(b"%PDF"):
                        log(f"  skip (not a PDF): {item.title}")
                        continue
                    save(doc_type, item.title, item.issued_on, item.page_url, pdf_url, pdf)

                if doc_type != "master_circular":
                    continue
                # Each chapter becomes its own document, so citations open the right PDF.
                for part_title, part_url in find_linked_parts(pdf):
                    if have(part_url):
                        continue
                    part = client.get(part_url).content
                    if part.startswith(b"%PDF"):
                        title = f"{item.title} — {part_title}"
                        save(doc_type, title, item.issued_on, part_url, part_url, part)
    finally:
        client.close()
    return added
