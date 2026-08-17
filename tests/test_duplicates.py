"""The same row twice: noise, or a finding.

A row can appear twice for reasons that have nothing to do with what was
billed — a second text layer left behind by OCR, or a row on a page seam
rendered onto both pages. Those are removed.

A row can also appear twice because the invoice genuinely bills it twice.
That is an audit finding. Duplicate billing is one of the things this kind of
testing exists to catch, and it must survive extraction intact.

These tests exist to keep those two apart. If the second set ever starts
passing because everything identical is dropped, the tool has stopped being
useful for the thing it was built for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_source.reader import read_document
from sum_finding import SumFinder

from tests.duplicates import overlay_text_layer, repeat_line_elsewhere
from tests.multipage import split_across_pages

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "pdf"
SOURCE = PDF / "INV-2026-1006.pdf"


@pytest.fixture(scope="module")
def clean():
    document, _ = read_document(SOURCE)
    return document


@pytest.fixture(scope="module")
def overlaid(tmp_path_factory):
    out = tmp_path_factory.mktemp("duplicates")
    return overlay_text_layer(SOURCE, out / "overlaid.pdf")


@pytest.fixture(scope="module")
def genuine(tmp_path_factory):
    out = tmp_path_factory.mktemp("duplicates")
    return repeat_line_elsewhere(SOURCE, out / "genuine.pdf", line_number=2)


# --- artefacts, which are removed -----------------------------------------

def test_a_doubled_text_layer_reads_as_the_clean_document(clean, overlaid):
    """Two text layers, one document. The parse must not change."""
    document, _ = read_document(overlaid)

    assert document["lines"] == clean["lines"]
    assert document["totals"] == clean["totals"]


def test_doubled_text_is_not_left_in_a_description(overlaid):
    """The failure this guards against is 'RRU RRU radio radio unit unit'."""
    document, _ = read_document(overlaid)

    for line in document["lines"]:
        words = line.get("description", "").split()
        assert len(words) == len(set(words)) or len(words) < 2, (
            f"description carries repeated words: {line['description']!r}"
        )


def test_the_removal_is_recorded(overlaid):
    """Nothing is dropped without a record of it."""
    document, _ = read_document(overlaid)
    notes = document.get("removed_duplicates")

    assert notes, "words were removed but nothing was recorded"
    assert notes[0]["words"] > 0
    assert "coordinates" in notes[0]["reason"]


def test_a_clean_document_records_nothing(clean):
    assert "removed_duplicates" not in clean


def test_a_row_on_a_page_seam_is_not_counted_twice(tmp_path):
    """A row rendered onto both pages of a break is one row."""
    split = split_across_pages(SOURCE, tmp_path / "split.pdf", 368.0)
    document, _ = read_document(split)

    numbers = [line["line_number"] for line in document["lines"]]
    assert numbers == [1, 2, 3, 4, 5, 6]


# --- genuine duplicates, which are kept ------------------------------------

def test_a_genuinely_duplicated_line_survives(genuine):
    """The invoice bills line 2 twice. Both must reach the caller."""
    document, _ = read_document(genuine)

    numbers = [line["line_number"] for line in document["lines"]]
    assert numbers.count(2) == 2, (
        f"a duplicate billed line was removed: {numbers}"
    )
    assert len(document["lines"]) == 7


def test_a_genuine_duplicate_is_not_recorded_as_a_removal(genuine):
    document, _ = read_document(genuine)
    assert "removed_duplicates" not in document


def test_the_duplicate_makes_the_invoice_fail_its_arithmetic(genuine):
    """A line billed twice no longer agrees with the stated subtotal.

    This is the point of keeping it. The document now says one thing and its
    own lines say another, and the tool reports that rather than smoothing it
    over.
    """
    result = SumFinder.from_pdf(genuine).check()
    assert result.discrepancies, (
        "an invoice with a duplicated line reported no discrepancy"
    )
