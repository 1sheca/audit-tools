"""The harder sample set: multi-page documents carrying pictures.

`data/pdf-rich/` holds documents that behave the way supplier documents
actually behave. The tables run past the foot of a page and resume under a
reprinted set of column headings. A logo sits at the top of every page and a
footer at the bottom of every page. There is a signature, an approval stamp, a
watermark, a process drawing, a site plan and an escalation chart between the
figures. One document is a scan with no text in it at all.

Nothing here is decoration. Each of those elements is a way for a reader to
pick up something that is not a figure, or to lose a figure that is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_source.reader import NoTextLayer, read_document
from sum_finding import SumFinder
from evidence_generator import EvidenceGenerator

ROOT = Path(__file__).resolve().parent.parent
RICH = ROOT / "data" / "pdf-rich"

# What is deliberately wrong with each document.
ARITHMETIC_DEFECTS = {"RINV-2026-2002", "RPO-0089203"}
REFERENCE_DEFECTS = {"RINV-2026-2003", "RINV-2026-2005"}
SCAN = "RINV-2026-2006-scan"

if len(list(RICH.glob("*.pdf"))) < 13:
    raise RuntimeError(
        "data/pdf-rich is missing documents. They are part of this repository "
        "— restore them from source control, or rebuild with "
        "`python -m rich_documents.make`."
    )


def documents() -> list[Path]:
    return sorted(p for p in RICH.glob("*.pdf") if p.stem != SCAN)


@pytest.mark.parametrize("path", documents(), ids=lambda p: p.stem)
def test_every_document_parses(path):
    document, positions = read_document(path)

    assert document["document_id"] == path.stem, (
        "the document's own reference was not read back"
    )
    assert document["page_count"] >= 2, "this set is meant to be multi-page"
    assert positions, "no field was located on the page"


@pytest.mark.parametrize("path", documents(), ids=lambda p: p.stem)
def test_the_table_is_read_whole(path):
    """Every row of the table, wherever the page break falls."""
    document, _ = read_document(path)
    rows = document.get("lines") or document.get("rate_schedule") or []

    assert rows, "no table rows were read"

    numbers = [row["line_number"] for row in rows if "line_number" in row]
    if numbers:
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"line numbers are not continuous: {numbers}"
        )


def test_a_table_actually_crosses_a_page_break():
    """Guard the premise. If nothing spans a page, this set proves nothing."""
    spanning = []
    for path in documents():
        _, positions = read_document(path)
        pages = {
            position.page for key, position in positions.items()
            if key.startswith(("lines[", "rate_schedule["))
        }
        if len(pages) > 1:
            spanning.append(path.stem)

    assert len(spanning) >= 8, (
        f"only {len(spanning)} documents have a table spanning pages"
    )


def test_a_repeated_column_heading_is_not_read_as_a_row():
    """The headings are reprinted after each break. They are not data."""
    document, _ = read_document(RICH / "RINV-2026-2004.pdf")

    for line in document["lines"]:
        assert "DESCRIPTION" not in (line.get("description") or "").upper()
        assert isinstance(line["line_number"], int)


def test_the_page_footer_is_not_read_as_a_row():
    """A footer under a table is furniture, not a rate.

    The footer carries a page number. Read as a table row it becomes an item
    priced at 2.00, which is both wrong and entirely plausible-looking.
    """
    document, _ = read_document(RICH / "RCTR-4401.pdf")

    for term in document["rate_schedule"]:
        description = (term.get("description") or "").lower()
        assert "page" not in description
        assert "synthetic" not in description
        assert term["max_unit_price"] > 10, (
            f"a page number was read as a rate: {term}"
        )


def test_a_figure_printed_against_its_currency_is_still_read():
    """Purchase orders here print ORDER VALUE EUR and the amount touching."""
    document, _ = read_document(RICH / "RPO-0089201.pdf")

    assert document["order_value"] is not None
    assert document["order_value"] > 1000


@pytest.mark.parametrize("path", documents(), ids=lambda p: p.stem)
def test_arithmetic_finds_the_planted_defects_and_nothing_else(path):
    result = SumFinder.from_pdf(path).check()

    if path.stem in ARITHMETIC_DEFECTS:
        assert result.discrepancies, "a planted defect was not found"
    else:
        assert not result.discrepancies, (
            f"false positive: {[d.check for d in result.discrepancies]}"
        )


def test_a_missing_purchase_order_reference_is_absent_not_invented():
    document, _ = read_document(RICH / "RINV-2026-2005.pdf")
    assert document["po_reference"] is None


def test_a_purchase_order_that_does_not_exist_is_read_as_written():
    """The reader reports what the document says. It does not correct it."""
    document, _ = read_document(RICH / "RINV-2026-2003.pdf")

    assert document["po_reference"] == "RPO-0089999"
    assert not (RICH / "RPO-0089999.pdf").exists()


def test_the_scan_is_refused_rather_than_guessed_at():
    with pytest.raises(NoTextLayer):
        read_document(RICH / f"{SCAN}.pdf")


def test_evidence_cites_the_page_the_figure_is_printed_on():
    """Totals here sit on a later page than the invoice header."""
    path = RICH / "RINV-2026-2004.pdf"
    _, positions = read_document(path)

    assert positions["document_id"].page == 0
    assert positions["totals.grand_total"].page > 0, (
        "the grand total is on a later page and must be cited there"
    )

    pack = EvidenceGenerator.from_pdf(path)
    assert pack.cite("totals.grand_total") is not None


# ---------------------------------------------------------------------------
# Ground truth. The tests above check that the shape of the output is sensible.
# These check that the values are the values the document actually prints —
# a different question, and the one that matters.

LINE_SPEC = {
    "RINV-2026-2001": (26, 0), "RINV-2026-2002": (34, 3),
    "RINV-2026-2003": (21, 6), "RINV-2026-2004": (48, 1),
    "RINV-2026-2005": (30, 9), "RPO-0089201": (26, 0),
    "RPO-0089202": (48, 1), "RPO-0089203": (33, 4), "RPO-0089204": (19, 7),
}


@pytest.mark.parametrize("stem", sorted(LINE_SPEC), ids=lambda s: s)
def test_every_line_matches_what_was_printed(stem):
    """Compare each field against the value the generator put on the page."""
    from rich_documents.layout import catalogue_lines

    count, start = LINE_SPEC[stem]
    expected = catalogue_lines(count, start)
    document, _ = read_document(RICH / f"{stem}.pdf")
    actual = document["lines"]

    assert len(actual) == len(expected)

    # Purchase orders here print no line total column.
    fields = [("qty", "quantity"), ("unit_price", "unit_price"),
              ("net", "net_amount")]
    if not stem.startswith("RPO"):
        fields.append(("total", "line_total"))

    for want, got in zip(expected, actual):
        for want_key, got_key in fields:
            assert got.get(got_key) == pytest.approx(want[want_key]), (
                f"line {want['ln']} {got_key}"
            )
        assert got.get("description") == want["description"]
        assert got.get("unit_of_measure") == want["uom"]


def test_a_part_number_stays_in_the_description():
    """A number inside a description is not a figure in a column.

    "RRU 4415 radio unit" must not be read as "RRU radio unit". The part
    number is often the only thing separating two otherwise similar lines,
    and matching an invoice line to a PO line depends on it.
    """
    for stem in ("RINV-2026-2001", "RPO-0089201", "RCTR-4401"):
        document, _ = read_document(RICH / f"{stem}.pdf")
        rows = document.get("lines") or document["rate_schedule"]
        descriptions = [r.get("description", "") for r in rows]
        assert any("4415" in d for d in descriptions), (
            f"{stem}: the part number was dropped from the description"
        )


def test_contract_rate_schedules_match_what_was_printed():
    from rich_documents.make import RATE_SCHEDULE

    for stem in ("RCTR-4401", "RCTR-4402", "RCTR-4403"):
        document, _ = read_document(RICH / f"{stem}.pdf")
        schedule = document["rate_schedule"]

        assert len(schedule) == len(RATE_SCHEDULE)
        for (description, uom, rate), got in zip(RATE_SCHEDULE, schedule):
            assert got["description"] == description
            assert got["unit_of_measure"] == uom
            assert got["max_unit_price"] == pytest.approx(rate)
