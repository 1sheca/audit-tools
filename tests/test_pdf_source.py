"""The PDF reader must recover what the page actually says, defects included."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_source import NoTextLayer, read_all, read_document

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "pdf"

if len(list(PDF.glob("*.pdf"))) < 20:
    raise RuntimeError(
        "data/pdf is missing documents. The 20 sample PDFs are part of this "
        "repository — restore them from source control."
    )






def test_every_document_parses():
    parsed = read_all(PDF)
    assert len(parsed) == 20
    assert all(d["document_id"] for d, _ in parsed)


def test_each_layout_is_recognised():
    kinds = {read_document(PDF / f"{n}.pdf")[0]["document_type"]
             for n in ("INV-2026-1001", "PO-0089142", "CTR-3301")}
    assert kinds == {"invoice", "purchase_order", "contract"}


def test_invoice_lines_and_totals_are_read_from_the_page():
    doc, _ = read_document(PDF / "INV-2026-1005.pdf")
    assert doc["lines"][0]["unit_price"] == 1400.0
    assert doc["lines"][0]["quantity"] == 30.0
    assert doc["totals"]["subtotal"] == 42000.0
    assert doc["totals"]["grand_total"] == 52080.0


def test_contract_rate_schedule_is_read_from_the_page():
    doc, _ = read_document(PDF / "CTR-3302.pdf")
    assert doc["rate_schedule"][0]["max_unit_price"] == 1250.0
    assert doc["payment_terms"] == "Net 45"


def test_absent_field_stays_absent_rather_than_defaulting():
    doc, _ = read_document(PDF / "INV-2026-1009.pdf")
    assert "payment_terms" not in doc


def test_missing_purchase_order_reference_reads_as_none():
    doc, _ = read_document(PDF / "INV-2026-1007.pdf")
    assert doc["po_reference"] is None


def test_deliberate_defects_survive_the_round_trip():
    """A parser that silently corrects the document is worse than none."""
    bad_subtotal, _ = read_document(PDF / "INV-2026-1004.pdf")
    assert bad_subtotal["totals"]["subtotal"] == 23050.0

    transposed, _ = read_document(PDF / "INV-2026-1008.pdf")
    assert transposed["totals"]["grand_total"] == 87586.8


def test_positions_are_returned_for_located_fields():
    doc, positions = read_document(PDF / "INV-2026-1005.pdf")
    key = "lines[0].unit_price"
    assert key in positions
    box = positions[key]
    assert box.x1 > box.x0 and box.y1 > box.y0


def test_scan_without_text_layer_is_rejected(tmp_path):
    import pymupdf

    blank = pymupdf.open()
    blank.new_page()
    path = tmp_path / "scan.pdf"
    blank.save(path)
    blank.close()
    with pytest.raises(NoTextLayer):
        read_document(path)
