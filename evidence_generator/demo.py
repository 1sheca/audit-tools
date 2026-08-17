#!/usr/bin/env python3
"""Evidence generator demonstration.

    python -m evidence_generator.demo
    python -m evidence_generator.demo --snip      crop each citation from its page
    python -m evidence_generator.demo --markdown
    python -m evidence_generator.demo --json

Reads the PDFs in data/pdf/. Every citation carries the page and rectangle the
value was read from, which is what allows the evidence to be cropped from the
original document rather than merely asserted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from evidence_generator import EvidenceGenerator

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "pdf"
BAR = "=" * 78

INVOICE, PO, CONTRACT = "INV-2026-1005", "PO-0089146", "CTR-3302"

CONCLUSION = (
    "Invoiced unit price of 1,400.00 exceeds the contracted maximum of "
    "1,250.00 for 'Fibre trunk cable 500m', despite agreeing to the purchase "
    "order. Two-way matching would not detect this."
)


def build() -> EvidenceGenerator:
    return EvidenceGenerator.from_pdf(
        PDF / f"{INVOICE}.pdf", PDF / f"{PO}.pdf", PDF / f"{CONTRACT}.pdf"
    )


def cite_all(gen: EvidenceGenerator) -> None:
    # The three values the conclusion rests on.
    gen.cite("lines[0].unit_price", document_id=INVOICE, confidence=0.94,
             note="invoiced rate")
    gen.cite("lines[0].unit_price", document_id=PO, confidence=1.0,
             note="ordered rate")
    gen.cite("rate_schedule[0].max_unit_price", document_id=CONTRACT, confidence=0.88,
             note="contracted ceiling, Schedule 2")

    # Supporting context an auditor would expect to see cited.
    gen.cite("lines[0].description", document_id=INVOICE, confidence=0.96)
    gen.cite("po_reference", document_id=INVOICE, confidence=0.92)
    gen.cite("contract_reference", document_id=PO, confidence=1.0)
    gen.cite("totals.grand_total", document_id=INVOICE, confidence=0.93)
    gen.cite("payment_terms", document_id=CONTRACT)

    # A field that may or may not be present. Absence is recorded, not omitted.
    gen.try_cite("delivery_note_reference", document_id=INVOICE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--snip", action="store_true",
                    help="crop every located citation from its source page")
    args = ap.parse_args()

    if not PDF.exists() or not any(PDF.glob("*.pdf")):
        print("data/pdf is missing. The 20 sample documents are part of this repository.")
        return 1

    gen = build()
    cite_all(gen)
    pack = gen.pack(conclusion=CONCLUSION)

    if args.json:
        print(pack.to_json())
        return 0
    if args.markdown:
        print(pack.to_markdown())
        return 0

    print(BAR)
    print("EVIDENCE GENERATOR")
    print(BAR)
    print(f"  source             data/pdf/ (parsed from the page)")
    print(f"  pack               {pack.pack_id}")
    print(f"  documents          {', '.join(pack.documents)}")
    print(f"  source systems     {', '.join(sorted(pack.sources))}")
    print(f"  weakest citation   {pack.weakest_confidence}")
    print(f"  integrity hash     {pack.integrity_hash}")
    print()
    print(f"  conclusion: {pack.conclusion}")
    print()
    print(f"  {'SOURCE':<12}{'DOCUMENT':<16}{'FIELD':<32}{'VALUE':<13}{'CONF':<7}POSITION")
    print("  " + "-" * 88)
    for item in pack.items:
        conf = "-" if item.confidence is None else f"{item.confidence:.2f}"
        value = "absent" if item.value is None else str(item.value)
        if item.bounding_box:
            where = f"p{item.page + 1} [{item.bounding_box[0]:.0f},{item.bounding_box[1]:.0f}]"
        else:
            where = "-"
        print(f"  {item.source_system:<12}{item.document_id:<16}"
              f"{item.field_path:<32}{value[:12]:<13}{conf:<7}{where}")
    print("  " + "-" * 88)

    located = sum(1 for i in pack.items if i.bounding_box)
    print(f"  {len(pack.items)} citations, {located} located on the page.")
    print("  Each located citation can be cropped from its source document.")

    if args.snip:
        from search_and_snip import Document

        out = ROOT / "out" / "evidence"
        out.mkdir(parents=True, exist_ok=True)
        print()
        written = 0
        for n, item in enumerate(pack.items, start=1):
            if not item.bounding_box:
                continue
            with Document(PDF / f"{item.document_id}.pdf") as doc:
                from search_and_snip import Hit
                hit = Hit(str(item.value), item.page or 0, *item.bounding_box)
                target = out / f"{n:02d}-{item.document_id}-{item.field_path.replace('.', '_').replace('[', '').replace(']', '')}.png"
                doc.snip_row(hit, target, highlight=True)
                written += 1
        print(f"  {written} evidence snips written to out/evidence/")

    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
