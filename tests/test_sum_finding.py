"""Sum finding: the arithmetic must be exact and the tolerances distinct."""

from __future__ import annotations

from decimal import Decimal

from pathlib import Path

import pytest

from pdf_source import read_all
from sum_finding import SumFinder, money

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "pdf"

if len(list(PDF.glob("*.pdf"))) < 20:
    raise RuntimeError(
        "data/pdf is missing documents. The 20 sample PDFs are part of this "
        "repository — restore them from source control."
    )






@pytest.fixture(scope="module")
def docs():
    """Every document, parsed from its PDF."""
    return {d["document_id"]: d for d, _ in read_all(PDF)}


def test_money_never_passes_through_binary_float():
    assert money(0.1) + money(0.2) == Decimal("0.3")
    assert money("1250.00") * 30 == Decimal("37500.00")


def test_clean_invoice_balances(docs):
    report = SumFinder(docs["INV-2026-1001"]).check()
    assert report.balanced
    assert report.checks_run > 0


def test_subtotal_disagreeing_with_lines_is_material(docs):
    report = SumFinder(docs["INV-2026-1004"]).check()
    codes = {d.check for d in report.material}
    assert "subtotal" in codes


def test_transposed_grand_total_is_caught(docs):
    report = SumFinder(docs["INV-2026-1008"]).check()
    assert any(d.check == "grand_total" and d.severity == "material"
               for d in report.discrepancies)


def test_rounding_drift_is_separated_from_material_error(docs):
    report = SumFinder(docs["INV-2026-1006"]).check()
    assert report.discrepancies
    assert not report.material, "seven cents is drift, not a finding"


def test_tolerances_are_independent():
    doc = {
        "document_id": "T-1", "document_type": "invoice",
        "lines": [{"line_number": 1, "quantity": 1, "unit_price": 100.00,
                   "net_amount": 100.50}],
        "totals": {"subtotal": 100.50},
    }
    loose = SumFinder(doc, reporting_tolerance=Decimal("5.00")).check()
    tight = SumFinder(doc, reporting_tolerance=Decimal("0.10")).check()
    assert not loose.material
    assert tight.material


def test_purchase_order_value_is_checked_against_its_lines(docs):
    for doc_id in ("PO-0089142", "PO-0089147"):
        assert SumFinder(docs[doc_id]).check().balanced


def test_grand_total_is_checked_against_stated_components():
    """A wrong grand total must not be masked by an equally wrong subtotal."""
    doc = {
        "document_id": "T-2", "document_type": "invoice",
        "lines": [{"line_number": 1, "quantity": 2, "unit_price": 50.00,
                   "net_amount": 100.00, "tax_rate": 0.0, "tax_amount": 0.0}],
        "totals": {"subtotal": 100.00, "tax_total": 0.00, "grand_total": 999.00},
    }
    report = SumFinder(doc).check()
    assert any(d.check == "grand_total" for d in report.material)


def test_report_serialises(docs):
    payload = SumFinder(docs["INV-2026-1008"]).check().to_dict()
    assert payload["balanced"] is False
    assert payload["discrepancies"][0]["severity"] == "material"


def test_whole_population_runs_without_error(docs):
    reports = [SumFinder(d).check() for d in docs.values()]
    assert len(reports) == 20
    # A contract carries a rate schedule but no totals, so it contributes no
    # arithmetic checks. That is the correct answer for a contract, not a gap.
    assert all(r.checks_run == 0 for r in reports if r.document_type == "contract")
    assert all(r.checks_run >= 1 for r in reports if r.document_type != "contract")
    assert sum(r.checks_run for r in reports) >= 80


# ---------------------------------------------------------------------------
def test_material_error_is_caught_reading_the_page():
    report = SumFinder.from_pdf(PDF / "INV-2026-1008.pdf").check()
    assert any(d.check == "grand_total" for d in report.material)


def test_whole_pdf_population_checks():
    reports = [SumFinder.from_pdf(p).check() for p in sorted(PDF.glob("*.pdf"))]
    assert len(reports) == 20
    assert sum(r.checks_run for r in reports) > 80
