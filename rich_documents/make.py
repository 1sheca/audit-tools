"""The documents: five invoices, four purchase orders, three contracts, one scan.

Each is multi-page. Each carries pictures. Several carry a deliberate defect,
listed in DEFECTS below so a test can assert the tools still find it.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from rich_documents.graphics import (
    escalation_chart, flow_diagram, scan_of, site_plan,
)
from rich_documents.layout import (
    BODY_BOTTOM, MARGIN, OUT, PAGE, RIGHT, Sheet, catalogue_lines,
    money, table_header, table_row, totals_block,
)

SELLER = [
    "Apex Consulting Group",
    "Dublin, IE",
    "Account V-9034",
    "Tax reg. IE9825613K",
]

BUYER = [
    "Group Procurement",
    "Karaportti 3, Espoo, FI",
    "Tax reg. FI20114020",
]


# What is wrong with each document, and why it is here.
DEFECTS = {
    "RINV-2026-2002": "stated subtotal is 4,000.00 below the sum of its lines",
    "RINV-2026-2003": "quotes a purchase order that does not exist",
    "RINV-2026-2005": "no purchase order reference at all",
    "RPO-0089203": "order value does not agree with its own lines",
}


# ---------------------------------------------------------------------------
def invoice(reference: str, po_reference: str | None, line_count: int,
            start: int, *, subtotal_error: float = 0.0, mark: int = 0,
            issue: str = "2026-04-08", due: str = "2026-06-07",
            terms: str = "Net 60", watermark: str | None = None,
            diagram: bool = False) -> Path:
    sheet = Sheet("COMMERCIAL INVOICE · original", reference, mark)

    sheet.party("SELLER", SELLER, MARGIN)
    sheet.party("BILL TO", BUYER, 317)
    sheet.gap(86)

    for label, value, x in (
        ("INVOICE NUMBER", reference, MARGIN),
        ("ISSUE DATE", issue, 170),
        ("DUE DATE", due, 278),
        ("TERMS", terms, 386),
        ("CURRENCY", "EUR", 476),
    ):
        sheet.field(label, value, x)
    sheet.gap(40)

    sheet.field("PURCHASE ORDER REFERENCE",
                po_reference or "None quoted", MARGIN)
    sheet.gap(34)

    if watermark:
        sheet.watermark(watermark)

    lines = catalogue_lines(line_count, start)

    table_header(sheet)
    for line in lines:
        # Repeat the column headings whenever the table breaks onto a new page.
        if sheet.y + 18.4 > BODY_BOTTOM:
            sheet.new_page()
            table_header(sheet)
        table_row(sheet, line)

    if diagram:
        sheet.space(120)
        sheet.gap(18)
        flow_diagram(
            sheet.page,
            pymupdf.Rect(MARGIN, sheet.y, RIGHT, sheet.y + 70),
            ("Contract", "Purchase order", "Goods received", "Invoice"),
            "Document flow for this delivery.",
        )
        sheet.gap(86)

    net = round(sum(line["net"] for line in lines), 2)
    vat = round(sum(line["total"] - line["net"] for line in lines), 2)

    stated_net = round(net - subtotal_error, 2)
    totals_block(sheet, stated_net, vat, round(stated_net + vat, 2))

    sheet.space(150)
    sheet.gap(10)
    sheet.approval_stamp(RIGHT - 130, sheet.y,
                         ("APPROVED", "AP-2026-04", "Finance"))
    sheet.sign("R. Doyle", "Authorised signatory, Apex Consulting Group",
               seed=mark)

    return sheet.finish(
        OUT / f"{reference}.pdf",
        f"Remit to IBAN FI21 1234 5600 00{reference[-4:]} BIC NDEAFIHH",
    )


# ---------------------------------------------------------------------------
def purchase_order(reference: str, contract_reference: str, line_count: int,
                   start: int, *, value_error: float = 0.0,
                   mark: int = 1) -> Path:
    sheet = Sheet("PURCHASE ORDER", reference, mark)

    sheet.party("SUPPLIER", SELLER, MARGIN)
    sheet.party("DELIVER TO", ["Site A1, Espoo, FI", "Gate 4, 07:00-15:00"], 317)
    sheet.gap(86)

    for label, value, x in (
        ("PO NUMBER", reference, MARGIN),
        ("ORDER DATE", "2026-03-11", 170),
        ("DELIVERY BY", "2026-05-02", 278),
        ("CURRENCY", "EUR", 476),
    ):
        sheet.field(label, value, x)
    sheet.gap(40)

    sheet.field("CONTRACT REFERENCE", contract_reference, MARGIN)
    sheet.gap(34)

    lines = catalogue_lines(line_count, start)
    net = round(sum(line["net"] for line in lines), 2)

    sheet.label("ITEM SCHEDULE")
    sheet.gap(16)
    for name, x in (("ITEM", MARGIN), ("DESCRIPTION", 82), ("UOM", 272),
                    ("ORDERED", 313), ("UNIT PRICE", 352), ("NET", 439)):
        sheet.page.insert_text((x, sheet.y), name, fontsize=7.2, fontname="hebo")
    sheet.page.draw_line((MARGIN, sheet.y + 4), (RIGHT, sheet.y + 4),
                         color=(0.7, 0.7, 0.7), width=0.6)
    sheet.gap(25)

    for line in lines:
        if sheet.y + 18.4 > BODY_BOTTOM:
            sheet.new_page()
            for name, x in (("ITEM", MARGIN), ("DESCRIPTION", 82), ("UOM", 272),
                            ("ORDERED", 313), ("UNIT PRICE", 352), ("NET", 439)):
                sheet.page.insert_text((x, sheet.y), name, fontsize=7.2,
                                       fontname="hebo")
            sheet.gap(25)
        p = sheet.page
        p.insert_text((MARGIN, sheet.y), str(line["ln"]), fontsize=8.4, fontname="helv")
        p.insert_text((82, sheet.y), line["description"], fontsize=8.4, fontname="helv")
        p.insert_text((272, sheet.y), line["uom"], fontsize=8.4, fontname="helv")
        p.insert_text((324, sheet.y), str(line["qty"]), fontsize=8.4, fontname="helv")
        for value, edge in ((line["unit_price"], 404), (line["net"], 453)):
            text = money(value)
            width = pymupdf.get_text_length(text, fontname="helv", fontsize=8.4)
            p.insert_text((edge - width, sheet.y), text, fontsize=8.4, fontname="helv")
        sheet.gap(18.4)

    stated = round(net - value_error, 2)
    sheet.space(40)
    sheet.gap(18)
    text = money(stated)
    width = pymupdf.get_text_length(text, fontname="hebo", fontsize=10)
    sheet.page.insert_text((410, sheet.y), "ORDER VALUE EUR", fontsize=10,
                           fontname="hebo")
    sheet.page.insert_text((540 - width, sheet.y), text, fontsize=10,
                           fontname="hebo")
    sheet.gap(30)

    sheet.space(180)
    sheet.gap(14)
    sheet.label("DELIVERY LOCATION")
    sheet.gap(14)
    site_plan(sheet.page,
              pymupdf.Rect(MARGIN, sheet.y, MARGIN + 300, sheet.y + 120))
    sheet.approval_stamp(RIGHT - 130, sheet.y + 20,
                         ("RELEASED", "PROC-2026", "Buyer"))
    sheet.gap(138)

    sheet.sign("M. Laine", "Procurement authority", seed=mark + 2)

    return sheet.finish(OUT / f"{reference}.pdf",
                        "Purchase order raised under the referenced agreement.")


# ---------------------------------------------------------------------------
CLAUSES = [
    ("1. Scope", "The Supplier shall provide the equipment and services set "
     "out in the rate schedule, at the sites notified by the Buyer from time "
     "to time. Delivery of any item is subject to a purchase order raised "
     "under this agreement and quoting its reference."),
    ("2. Prices", "Unit rates are those stated in the rate schedule below. "
     "Charges in excess of these values require prior written variation "
     "signed by both parties. No invoice shall be settled at a unit rate "
     "above the maximum stated, whatever a purchase order may say."),
    ("3. Payment", "Correctly rendered invoices shall be settled on Net 60 "
     "terms from the date of receipt, provided the invoice quotes a valid "
     "purchase order reference and the goods have been received."),
    ("4. Records", "The Supplier shall retain records supporting each invoice "
     "for six years and shall make them available for audit on reasonable "
     "notice."),
    ("5. Variation", "No variation of this agreement is effective unless in "
     "writing and signed by an authorised representative of each party."),
]

RATE_SCHEDULE = [
    ("RRU 4415 radio unit", "EA", 1250.00),
    ("Fibre trunk cable 500m", "EA", 1250.00),
    ("Installation services", "HR", 95.00),
    ("Site survey", "DAY", 640.00),
    ("Antenna mount bracket", "EA", 78.50),
    ("Baseband module BB6630", "EA", 3180.00),
    ("Microwave link 80GHz", "EA", 4120.00),
    ("Commissioning and test", "DAY", 720.00),
    ("Power distribution unit", "EA", 890.00),
    ("Cabinet thermal kit", "EA", 445.00),
    ("Tower climb crew", "DAY", 1180.00),
    ("Spare parts kit A", "EA", 336.00),
    ("Optical patch panel", "EA", 214.00),
    ("Grounding kit", "EA", 96.50),
    ("Remote monitoring licence", "YR", 1540.00),
    ("Out of hours callout", "EA", 1260.00),
    ("Transport and logistics", "EA", 480.00),
    ("Decommissioning", "DAY", 690.00),
]


def contract(reference: str, *, mark: int = 2) -> Path:
    sheet = Sheet("MASTER SUPPLY AGREEMENT", reference, mark)

    sheet.party("COUNTERPARTY", SELLER, MARGIN)
    sheet.gap(76)

    for label, value, x in (
        ("CONTRACT REFERENCE", reference, MARGIN),
        ("EFFECTIVE DATE", "2026-01-01", 190),
        ("EXPIRY DATE", "2027-12-31", 320),
        ("GOVERNING LAW", "Finland", 450),
    ):
        sheet.field(label, value, x)
    sheet.gap(42)

    for heading, text in CLAUSES:
        sheet.space(46)
        sheet.label(heading)
        sheet.gap(14)
        sheet.paragraph(text)
        sheet.gap(8)

    sheet.space(140)
    sheet.gap(16)
    sheet.label("RATE SCHEDULE")
    sheet.gap(18)
    for name, x in (("ITEM DESCRIPTION", MARGIN), ("UOM", 300),
                    ("MAXIMUM UNIT RATE", 400)):
        sheet.page.insert_text((x, sheet.y), name, fontsize=7.2, fontname="hebo")
    sheet.page.draw_line((MARGIN, sheet.y + 4), (RIGHT, sheet.y + 4),
                         color=(0.7, 0.7, 0.7), width=0.6)
    sheet.gap(22)

    for description, uom, rate in RATE_SCHEDULE:
        if sheet.y + 18 > BODY_BOTTOM:
            sheet.new_page()
            for name, x in (("ITEM DESCRIPTION", MARGIN), ("UOM", 300),
                            ("MAXIMUM UNIT RATE", 400)):
                sheet.page.insert_text((x, sheet.y), name, fontsize=7.2,
                                       fontname="hebo")
            sheet.gap(22)
        sheet.page.insert_text((MARGIN, sheet.y), description, fontsize=8.4,
                               fontname="helv")
        sheet.page.insert_text((300, sheet.y), uom, fontsize=8.4, fontname="helv")
        text = money(rate)
        width = pymupdf.get_text_length(text, fontname="helv", fontsize=8.4)
        sheet.page.insert_text((480 - width, sheet.y), text, fontsize=8.4,
                               fontname="helv")
        sheet.gap(18)

    sheet.space(150)
    sheet.gap(20)
    sheet.label("ESCALATION")
    sheet.gap(16)
    escalation_chart(sheet.page,
                     pymupdf.Rect(MARGIN, sheet.y, RIGHT, sheet.y + 110))
    sheet.gap(126)

    sheet.space(200)
    sheet.gap(10)
    sheet.label("SIGNED FOR AND ON BEHALF OF THE PARTIES")
    sheet.gap(24)
    sheet.sign("R. Doyle", "Apex Consulting Group", seed=mark)
    sheet.sign("M. Laine", "Group Procurement", seed=mark + 4)

    return sheet.finish(OUT / f"{reference}.pdf",
                        "Master agreement. Rate schedule applies to all orders.")


# ---------------------------------------------------------------------------
def scanned_copy(source: Path, reference: str) -> Path:
    """A document that exists only as an image — no text layer at all."""
    out = pymupdf.open()
    with pymupdf.open(source) as original:
        for page in original:
            image = scan_of(page)
            new_page = out.new_page(width=PAGE.width, height=PAGE.height)
            new_page.insert_image(new_page.rect, pixmap=image)
    path = OUT / f"{reference}.pdf"
    out.save(path)
    out.close()
    return path


# ---------------------------------------------------------------------------
def build_all() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    for existing in OUT.glob("*.pdf"):
        existing.unlink()

    made = []

    made.append(invoice("RINV-2026-2001", "RPO-0089201", 26, 0,
                        mark=0, diagram=True))
    made.append(invoice("RINV-2026-2002", "RPO-0089201", 34, 3,
                        subtotal_error=4000.00, mark=0))
    made.append(invoice("RINV-2026-2003", "RPO-0089999", 21, 6,
                        mark=0, watermark="COPY"))
    made.append(invoice("RINV-2026-2004", "RPO-0089202", 48, 1,
                        mark=0, diagram=True, terms="Net 30",
                        due="2026-05-08"))
    made.append(invoice("RINV-2026-2005", None, 30, 9, mark=0))

    made.append(purchase_order("RPO-0089201", "RCTR-4401", 26, 0))
    made.append(purchase_order("RPO-0089202", "RCTR-4401", 48, 1))
    made.append(purchase_order("RPO-0089203", "RCTR-4402", 33, 4,
                               value_error=2500.00))
    made.append(purchase_order("RPO-0089204", "RCTR-4403", 19, 7))

    made.append(contract("RCTR-4401"))
    made.append(contract("RCTR-4402"))
    made.append(contract("RCTR-4403"))

    made.append(scanned_copy(OUT / "RINV-2026-2001.pdf", "RINV-2026-2006-scan"))

    return made


if __name__ == "__main__":
    paths = build_all()
    with pymupdf.open(paths[0]) as sample:
        _ = sample.page_count
    print(f"wrote {len(paths)} documents to {OUT}/")
    for path in paths:
        with pymupdf.open(path) as document:
            print(f"  {path.name:26} {document.page_count} pages")
