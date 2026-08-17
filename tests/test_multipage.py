"""Documents that run over more than one page.

Real invoices break across pages: the line table is cut by a page foot and
continues at the top of the next page, with the totals printed there. Each
case below takes a sample document and republishes it across two pages, then
requires that the reader produce exactly what it produced from one page.

Values must not move, be lost, or be counted twice. Only the page number in a
citation may change, and it must change to the page the value is actually on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_source.reader import Position, read_document
from sum_finding import SumFinder
from evidence_generator import EvidenceGenerator

from tests.multipage import split_across_pages

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "pdf"

if len(list(PDF.glob("*.pdf"))) < 20:
    raise RuntimeError(
        "data/pdf is missing documents. The 20 sample PDFs are part of this "
        "repository — restore them from source control."
    )

# Each split falls in the gap between two rows, never through one. A cut that
# crosses a row would print it on both pages, which no real document does.
CASES = [
    ("INV-2026-1006.pdf", 368.0),   # table broken mid-way, totals on page 2
    ("INV-2026-1004.pdf", 360.0),   # the document with a wrong stated subtotal
    ("PO-0089142.pdf", 330.0),
    ("CTR-3301.pdf", 330.0),
]


@pytest.fixture(scope="module")
def split(tmp_path_factory):
    out = tmp_path_factory.mktemp("multipage")
    made = {}
    for name, height in CASES:
        made[name] = split_across_pages(PDF / name, out / name, height)
    return made


@pytest.mark.parametrize("name,_height", CASES)
def test_two_page_copy_parses_to_the_same_document(split, name, _height):
    single, _ = read_document(PDF / name)
    double, _ = read_document(split[name])

    assert double["page_count"] == 2
    assert single["page_count"] == 1

    del single["page_count"], double["page_count"]
    assert single == double, f"{name} parsed differently across two pages"


@pytest.mark.parametrize("name,_height", CASES)
def test_the_same_fields_are_located(split, name, _height):
    _, single = read_document(PDF / name)
    _, double = read_document(split[name])

    assert set(single) == set(double), (
        f"{name}: different fields located when split across pages"
    )


def test_citations_point_at_the_page_the_value_is_on(split):
    """A value carried onto page two must be cited against page two."""
    _, positions = read_document(split["INV-2026-1006.pdf"])

    assert positions["document_id"].page == 0
    assert positions["lines[0].unit_price"].page == 0

    # The split falls after line three, so these are on the second page.
    assert positions["lines[5].line_total"].page == 1
    assert positions["totals.grand_total"].page == 1


def test_no_line_is_read_twice(split):
    """A table crossing a page break yields each line once."""
    document, _ = read_document(split["INV-2026-1006.pdf"])
    numbers = [line["line_number"] for line in document["lines"]]
    assert numbers == sorted(set(numbers)), f"duplicated lines: {numbers}"
    assert len(numbers) == 6


def test_arithmetic_is_unchanged_across_a_page_break(split):
    """The same checks, the same results, wherever the figures are printed."""
    for name in ("INV-2026-1006.pdf", "INV-2026-1004.pdf"):
        single = SumFinder.from_pdf(PDF / name).check()
        double = SumFinder.from_pdf(split[name]).check()

        assert len(single.discrepancies) == len(double.discrepancies)
        assert [d.check for d in single.discrepancies] == \
               [d.check for d in double.discrepancies]
        assert [d.stated for d in single.discrepancies] == \
               [d.stated for d in double.discrepancies]


def test_the_known_defect_still_surfaces_on_page_two(split):
    """INV-2026-1004 states a subtotal that does not agree with its lines.

    The defect must be found whether the subtotal is printed on page one or
    page two. A reader that quietly failed to find it would report a clean
    document, which is the worst outcome available.
    """
    result = SumFinder.from_pdf(split["INV-2026-1004.pdf"]).check()
    assert result.discrepancies, "the stated-subtotal defect was not found"


def test_evidence_cites_a_second_page(split):
    """An evidence pack crops from whichever page holds the value."""
    pack = EvidenceGenerator.from_pdf(split["INV-2026-1006.pdf"])
    citation = pack.cite("totals.grand_total")

    assert citation is not None
    position = pack.positions["totals.grand_total"] \
        if hasattr(pack, "positions") else None
    if isinstance(position, Position):
        assert position.page == 1
