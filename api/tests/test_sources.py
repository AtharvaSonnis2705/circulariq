from datetime import date

from circulariq.ingest.sources import parse_listing, parse_pdf_url, slugify

LISTING_HTML = """
<table id='sample_1'><thead><tr><th>Date</th><th>Title</th></tr></thead><tbody>
<tr role='row' class='odd'>
  <td>Sep 28, 2026</td>
  <td><a href="https://www.sebi.gov.in/legal/master-circulars/sep-2026/master-circular-for-debenture-trustees_104743.html"
         title="Master Circular for Debenture Trustees"> Master Circular for Debenture Trustees</a>
</tr>
<tr role='row' class='even'>
  <td>Jul 14, 2026</td>
  <td><a href="/legal/master-circulars/jul-2026/master-circular-for-merchant-bankers_102815.html"
         title="Master Circular for Merchant Bankers">Master Circular for Merchant Bankers</a>
</tr>
<tr><td>not a date</td><td><a href="/x.html">junk</a></td></tr>
</tbody></table>
"""

DETAIL_HTML = """
<iframe src='../../../web/?file=https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1790593347737.pdf'
        width='100%' title="Master Circular for Debenture Trustees"></iframe>
"""


def test_parse_listing_reads_rows_and_skips_junk() -> None:
    items = parse_listing(LISTING_HTML, "master_circular")
    assert [i.title for i in items] == [
        "Master Circular for Debenture Trustees",
        "Master Circular for Merchant Bankers",
    ]
    assert items[0].issued_on == date(2026, 9, 28)
    assert items[1].page_url.startswith("https://www.sebi.gov.in/legal/master-circulars/jul-2026/")


def test_parse_pdf_url_from_iframe_viewer() -> None:
    url = "https://www.sebi.gov.in/legal/master-circulars/sep-2026/x_104743.html"
    assert parse_pdf_url(DETAIL_HTML, url) == (
        "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/1790593347737.pdf"
    )
    assert parse_pdf_url("<p>no pdf here</p>", url) is None


def test_slugify() -> None:
    assert (
        slugify(
            "https://www.sebi.gov.in/legal/master-circulars/sep-2026/master-circular-for-debenture-trustees_104743.html"
        )
        == "master-circular-for-debenture-trustees_104743"
    )


def _pdf_with_links(pages: int, links: list[tuple[str, str]]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    page = doc[0]
    for i, (label, uri) in enumerate(links):
        rect = pymupdf.Rect(72, 72 + i * 20, 400, 88 + i * 20)
        page.insert_text((rect.x0, rect.y1 - 4), label)
        page.insert_link({"kind": pymupdf.LINK_URI, "from": rect, "uri": uri})
    return doc.tobytes()


def test_cover_letter_parts_are_found() -> None:
    from circulariq.ingest.sources import find_linked_parts

    pdf = _pdf_with_links(
        4,
        [
            (
                "Chapter 1 - Trading",
                "https://www.sebi.gov.in/sebi_data/commondocs/dec-2024/ch1.pdf",
            ),
            ("SEBI home", "http://www.sebi.gov.in/"),
            ("Chapter 1 again", "https://www.sebi.gov.in/sebi_data/commondocs/dec-2024/ch1.pdf"),
        ],
    )
    assert find_linked_parts(pdf) == [
        ("Chapter 1 - Trading", "https://www.sebi.gov.in/sebi_data/commondocs/dec-2024/ch1.pdf")
    ]


def test_long_documents_links_are_references_not_parts() -> None:
    from circulariq.ingest.sources import find_linked_parts

    pdf = _pdf_with_links(40, [("ref", "https://www.sebi.gov.in/sebi_data/attachdocs/x.pdf")])
    assert find_linked_parts(pdf) == []
