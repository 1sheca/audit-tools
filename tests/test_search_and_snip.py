"""Search and snip: located text must be where the tool says it is."""

from __future__ import annotations

from pathlib import Path

import pytest

from search_and_snip import Document, NoTextLayer, find_pdfs

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "pdf"

if len(list(PDF.glob("*.pdf"))) < 20:
    raise RuntimeError(
        "data/pdf is missing documents. The 20 sample PDFs are part of this "
        "repository — restore them from source control."
    )




def test_population_rendered():
    assert len(list(find_pdfs(PDF))) == 20


def test_literal_search_returns_a_position():
    with Document(PDF / "INV-2026-1005.pdf") as doc:
        hits = doc.search("1,400.00")
        assert hits
        assert hits[0].width > 0 and hits[0].height > 0


def test_missing_text_returns_empty_not_error():
    with Document(PDF / "INV-2026-1005.pdf") as doc:
        assert doc.search("this string is not on the page") == []


def test_pattern_search_finds_references_by_shape():
    with Document(PDF / "PO-0089142.pdf") as doc:
        hits = doc.search_pattern(r"^CTR-\d{4}$")
        assert any(h.text == "CTR-3301" for h in hits)


def test_label_anchored_lookup_reads_the_value_below():
    with Document(PDF / "INV-2026-1005.pdf") as doc:
        hit = doc.value_beside("PURCHASE ORDER REFERENCE")
        assert hit is not None
        assert "0089146" in hit.text


def test_row_widening_returns_surrounding_context():
    with Document(PDF / "INV-2026-1005.pdf") as doc:
        hit = doc.search("1,400.00")[0]
        row = doc.row_containing(hit)
        assert row.width > hit.width
        assert "Fibre trunk cable" in row.text


def test_snip_writes_a_png(tmp_path):
    with Document(PDF / "CTR-3302.pdf") as doc:
        hit = doc.search("1,250.00")[0]
        out = doc.snip(hit, tmp_path / "snip.png")
        assert out.exists() and out.stat().st_size > 0


def test_highlight_does_not_modify_the_source(tmp_path):
    source = PDF / "INV-2026-1001.pdf"
    before = source.read_bytes()
    with Document(source) as doc:
        doc.snip(doc.search("INV-2026-1001")[0], tmp_path / "h.png", highlight=True)
    assert source.read_bytes() == before


def test_every_document_carries_a_locatable_reference():
    for path in find_pdfs(PDF):
        with Document(path) as doc:
            assert doc.search(path.stem), f"{path.stem} not found on its own page"


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        Document(PDF / "does-not-exist.pdf")
