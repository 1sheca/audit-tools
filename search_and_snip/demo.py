#!/usr/bin/env python3
"""Search and snip demonstration.

    python -m search_and_snip.demo
    python -m search_and_snip.demo --scan
"""

from __future__ import annotations

import argparse
from pathlib import Path

from search_and_snip import Document, find_pdfs

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "pdf"
OUT = ROOT / "out" / "snips"
BAR = "=" * 78


def scan_all() -> int:
    """Locate the same field across every document type."""
    print(BAR)
    print("SEARCH AND SNIP  ·  locating references across the population")
    print(BAR)
    print(f"  {'DOCUMENT':<18}{'PAGE':<7}{'FOUND':<10}POSITION")
    print("  " + "-" * 66)

    found = 0
    for path in find_pdfs(PDF):
        with Document(path) as doc:
            hits = doc.search_pattern(r"^(INV|PO|CTR)-\d")
            if hits:
                found += 1
                h = hits[0]
                print(f"  {path.stem:<18}{h.page + 1:<7}{h.text:<10}"
                      f"[{h.x0:.0f},{h.y0:.0f}]")
    print("  " + "-" * 66)
    print(f"  reference located on {found} of {len(list(find_pdfs(PDF)))} documents")
    print(BAR)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true",
                    help="locate the document reference on every PDF")
    args = ap.parse_args()

    if not PDF.exists():
        print("data/pdf is missing. The 20 sample documents are part of this repository.")
        return 1
    if args.scan:
        return scan_all()

    OUT.mkdir(parents=True, exist_ok=True)

    print(BAR)
    print("SEARCH AND SNIP  ·  turning a figure into showable evidence")
    print(BAR)

    # 1. literal search, then crop the whole row for context
    with Document(PDF / "INV-2026-1005.pdf") as doc:
        hit = doc.search("1,400.00")[0]
        row = doc.row_containing(hit)
        out = doc.snip_row(hit, OUT / "01-invoiced-rate.png", highlight=True)
        print(f"\n  1  literal search on the invoice")
        print(f"     found      {hit.describe()}")
        print(f"     row        {row.text}")
        print(f"     snip       {out.relative_to(ROOT)}")

    # 2. the contracted ceiling on a different document with a different layout
    with Document(PDF / "CTR-3302.pdf") as doc:
        hit = doc.search("1,250.00")[0]
        out = doc.snip_row(hit, OUT / "02-contracted-ceiling.png", highlight=True)
        print(f"\n  2  same figure type, different document layout")
        print(f"     found      {hit.describe()}")
        print(f"     snip       {out.relative_to(ROOT)}")

    # 3. label-anchored lookup: read a value by its label, not its value
    with Document(PDF / "INV-2026-1005.pdf") as doc:
        terms = doc.value_beside("TERMS")
        po = doc.value_beside("PURCHASE ORDER REFERENCE")
        print(f"\n  3  label-anchored lookup, value not known in advance")
        print(f"     TERMS      -> {terms.text if terms else 'not found'}")
        print(f"     PO REF     -> {po.text if po else 'not found'}")
        if po:
            doc.snip(po, OUT / "03-po-reference.png", highlight=True)
            print(f"     snip       out/snips/03-po-reference.png")

    # 4. pattern search for anything with a known shape
    with Document(PDF / "INV-2026-1001.pdf") as doc:
        tax_ids = doc.search_pattern(r"^[A-Z]{2}\d{8,}$")
        print(f"\n  4  pattern search for tax registration numbers")
        for h in tax_ids[:3]:
            print(f"     {h.describe()}")

    # 5. the limitation, stated plainly
    print(f"\n  5  limitation")
    print("     Every result above depends on a text layer. A scanned or")
    print("     photographed document raises NoTextLayer and must go to a")
    print("     cloud extraction service instead.")

    print()
    print(BAR)
    print(f"  snips written to {OUT.relative_to(ROOT)}/")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
