"""Evidence generator: provenance must be accurate or it is worse than absent."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from evidence_generator import EvidenceGenerator, FieldNotFound
from pdf_source import read_all

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


def test_citation_records_source_document_and_value(docs):
    gen = EvidenceGenerator(docs["INV-2026-1005"])
    item = gen.cite("lines[0].unit_price")
    assert item.source_system == "SharePoint"
    assert item.document_id == "INV-2026-1005"
    assert item.document_type == "invoice"
    assert item.value == 1400.0


def test_nested_and_indexed_paths_resolve(docs):
    gen = EvidenceGenerator(docs["CTR-3302"])
    assert gen.cite("counterparty.name").value == "Delta Cabling Oy"
    assert gen.cite("rate_schedule[1].description").value


def test_missing_field_raises_rather_than_citing_nothing(docs):
    gen = EvidenceGenerator(docs["INV-2026-1001"])
    with pytest.raises(FieldNotFound):
        gen.cite("totals.withholding_tax")
    with pytest.raises(FieldNotFound):
        gen.cite("lines[99].unit_price")


def test_absence_is_recorded_explicitly_by_try_cite(docs):
    gen = EvidenceGenerator(docs["INV-2026-1009"])
    assert gen.try_cite("payment_terms") is None
    pack = gen.pack()
    assert pack.items[0].value is None
    assert "absent" in pack.items[0].note


def test_pack_spans_multiple_documents_and_systems(docs):
    gen = EvidenceGenerator(docs["INV-2026-1005"], docs["PO-0089146"], docs["CTR-3302"])
    gen.cite("lines[0].unit_price", document_id="INV-2026-1005")
    gen.cite("lines[0].unit_price", document_id="PO-0089146")
    gen.cite("rate_schedule[0].max_unit_price", document_id="CTR-3302")
    pack = gen.pack(conclusion="rate breach")
    assert pack.sources == {"SharePoint", "SAP", "CLM"}
    assert len(pack.documents) == 3


def test_weakest_confidence_is_the_minimum_not_the_average(docs):
    gen = EvidenceGenerator(docs["INV-2026-1001"])
    gen.cite("document_id", confidence=0.99)
    gen.cite("issue_date", confidence=0.99)
    gen.cite("seller.name", confidence=0.55)
    assert gen.pack().weakest_confidence == 0.55


def test_integrity_hash_changes_when_evidence_changes(docs):
    gen = EvidenceGenerator(docs["INV-2026-1001"])
    gen.cite("document_id")
    first = gen.pack().integrity_hash
    gen.cite("issue_date")
    assert gen.pack().integrity_hash != first


def test_pack_serialises_to_json_and_markdown(docs):
    gen = EvidenceGenerator(docs["INV-2026-1001"])
    gen.cite("totals.grand_total", confidence=0.9)
    pack = gen.pack(conclusion="agrees")
    assert json.loads(pack.to_json())["conclusion"] == "agrees"
    assert "| SharePoint |" in pack.to_markdown()


def test_unknown_document_id_is_rejected(docs):
    gen = EvidenceGenerator(docs["INV-2026-1001"])
    with pytest.raises(FieldNotFound):
        gen.cite("document_id", document_id="PO-9999999")


# ---------------------------------------------------------------------------
def test_citations_from_pdf_carry_page_and_rectangle():
    gen = EvidenceGenerator.from_pdf(PDF / "INV-2026-1005.pdf")
    item = gen.cite("lines[0].unit_price")
    assert item.value == 1400.0
    assert item.page == 0
    assert item.bounding_box is not None
    x0, y0, x1, y1 = item.bounding_box
    assert x1 > x0 and y1 > y0


def test_contract_ceiling_is_read_from_the_page(docs):
    """The value cited is the one printed in the contract's rate schedule."""
    gen = EvidenceGenerator.from_pdf(PDF / "CTR-3302.pdf")
    assert gen.cite("rate_schedule[0].max_unit_price").value == 1250.0


def test_pack_across_three_pdfs_supports_a_rate_breach():
    gen = EvidenceGenerator.from_pdf(
        PDF / "INV-2026-1005.pdf", PDF / "PO-0089146.pdf", PDF / "CTR-3302.pdf"
    )
    invoiced = gen.cite("lines[0].unit_price", document_id="INV-2026-1005")
    ordered = gen.cite("lines[0].unit_price", document_id="PO-0089146")
    ceiling = gen.cite("rate_schedule[0].max_unit_price", document_id="CTR-3302")
    assert invoiced.value > ceiling.value
    assert ordered.value == ceiling.value
    pack = gen.pack(conclusion="rate breach")
    assert len(pack.documents) == 3
    assert all(i.bounding_box for i in pack.items)
