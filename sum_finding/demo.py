#!/usr/bin/env python3
"""Sum finding demonstration.

    python -m sum_finding.demo
    python -m sum_finding.demo --verbose
    python -m sum_finding.demo --document INV-2026-1004

Reads the PDFs in data/pdf/. The figures checked are the ones printed on the
page, read back out of it.
"""

from __future__ import annotations

import argparse

from pathlib import Path

from sum_finding import SumFinder

BAR = "=" * 78


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--document", help="check a single document by id")
    args = ap.parse_args()

    pdf_dir = Path(__file__).resolve().parent.parent / "data" / "pdf"

    if not pdf_dir.exists() or not any(pdf_dir.glob("*.pdf")):
        print("data/pdf is missing. The 20 sample documents are part of this repository.")
        return 1

    paths = sorted(pdf_dir.glob("*.pdf"))
    if args.document:
        paths = [p for p in paths if p.stem == args.document]
        if not paths:
            print(f"No PDF for {args.document}")
            return 1

    print(BAR)
    print("SUM FINDING  ·  arithmetic verification")
    print(BAR)
    print("  rounding tolerance     0.02   absorbs legitimate half-cent differences")
    print("  reporting tolerance    1.00   below this, a difference is not raised")
    print("  arithmetic             Decimal throughout, never binary floating point")
    print(f"  source                 data/pdf/ ({len(paths)} documents, parsed from the page)")
    print()

    reports = [SumFinder.from_pdf(p).check() for p in paths]

    print(f"  {'DOCUMENT':<18}{'TYPE':<17}{'CHECKS':<9}{'RESULT':<17}DETAIL")
    print("  " + "-" * 74)

    for r in reports:
        if r.checks_run == 0:
            # Nothing was checked. Reporting that as agreement would overstate
            # the assurance given — a contract has a rate schedule, not totals.
            result, detail = "not applicable", "no totals on the document"
        elif r.balanced:
            result, detail = "agrees", ""
        elif r.material:
            result = "DISCREPANCY"
            detail = r.material[0].check
            if len(r.discrepancies) > 1:
                detail += f" +{len(r.discrepancies) - 1}"
        else:
            result = "rounding"
            detail = r.discrepancies[0].check
        print(f"  {r.document_id:<18}{r.document_type:<17}{r.checks_run:<9}{result:<17}{detail}")

    print("  " + "-" * 74)

    total_checks = sum(r.checks_run for r in reports)
    not_applicable = [r for r in reports if r.checks_run == 0]
    checked = [r for r in reports if r.checks_run > 0]
    clean = [r for r in checked if r.balanced]
    material = [r for r in checked if r.material]
    rounding_only = [r for r in checked if r.discrepancies and not r.material]

    print(f"  {len(reports)} documents  ·  {len(checked)} carried figures to check  ·  "
          f"{len(not_applicable)} not applicable")
    print(f"  {total_checks} arithmetic checks  ·  {len(clean)} agree  ·  "
          f"{len(material)} with material discrepancies  ·  "
          f"{len(rounding_only)} rounding only")

    if args.verbose:
        for r in reports:
            if r.discrepancies:
                print()
                print(f"  {r.document_id}")
                for d in r.discrepancies:
                    print(f"    {d.describe()}")
                print(f"    computed: net {r.computed['lines_net']}  "
                      f"tax {r.computed['lines_tax']}  "
                      f"gross {r.computed['lines_gross']}")
    else:
        print("  Run with --verbose for the individual discrepancies.")

    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
