"""Build a harder sample set: multi-page documents with pictures.

The twenty documents in `data/pdf/` are one page each, plain, and every field
sits where the reader expects it. That is a floor, not a test. Real documents
run over several pages, repeat their column headers after every page break,
carry a logo at the top and a signature at the bottom, print a stamp across
the middle, and put a drawing between the table and the totals.

Every document here still adds up in a way that can be checked, and several
carry a deliberate defect. The point is not that they are pretty. The point is
that the figures are harder to reach, and must still be reached.

Written to `data/pdf-rich/`. The original twenty are untouched.
"""

from __future__ import annotations

import math
from pathlib import Path

import pymupdf

from rich_documents.graphics import (
    escalation_chart, flow_diagram, logo, scan_of, signature, site_plan,
    stamp,
)

OUT = Path("data/pdf-rich")

PAGE = pymupdf.paper_rect("a4")
MARGIN = 57.0
RIGHT = PAGE.width - MARGIN
BODY_TOP = 118.0
BODY_BOTTOM = PAGE.height - 96.0

BOLD, PLAIN = "hebo", "helv"


# ---------------------------------------------------------------------------
class Sheet:
    """A document being written, which starts a new page when it runs out."""

    def __init__(self, title: str, reference: str, mark: int = 0):
        self.doc = pymupdf.open()
        self.title = title
        self.reference = reference
        self.mark = mark
        self.page: pymupdf.Page = None  # type: ignore[assignment]
        self.y = 0.0
        self.new_page()

    # -- page furniture -----------------------------------------------------
    def new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE.width, height=PAGE.height)
        self.page.insert_image(
            pymupdf.Rect(MARGIN, 44, MARGIN + 34, 78), pixmap=logo(self.mark)
        )
        self.page.insert_text((RIGHT - 96, 62), self.reference,
                              fontsize=9, fontname=BOLD)
        if self.doc.page_count == 1:
            self.page.insert_text((MARGIN + 44, 66), self.title,
                                  fontsize=13, fontname=BOLD)
        else:
            self.page.insert_text(
                (MARGIN + 44, 66), f"{self.title} · continued",
                fontsize=10, fontname=PLAIN, color=(0.4, 0.4, 0.4)
            )
        self.page.draw_line((MARGIN, 88), (RIGHT, 88),
                            color=(0.75, 0.75, 0.75), width=0.7)
        self.y = BODY_TOP

    def space(self, needed: float) -> None:
        """Break the page when the next block will not fit."""
        if self.y + needed > BODY_BOTTOM:
            self.new_page()

    def gap(self, amount: float) -> None:
        self.y += amount

    # -- text ---------------------------------------------------------------
    def label(self, text: str, x: float = MARGIN) -> None:
        self.page.insert_text((x, self.y), text, fontsize=7.5, fontname=BOLD,
                              color=(0.35, 0.35, 0.35))

    def value(self, text: str, x: float = MARGIN, size: float = 9) -> None:
        self.page.insert_text((x, self.y), text, fontsize=size, fontname=PLAIN)

    def field(self, label: str, value: str, x: float) -> None:
        """A label with its value printed beneath — the layout the reader reads."""
        self.page.insert_text((x, self.y), label, fontsize=7.5, fontname=BOLD,
                              color=(0.35, 0.35, 0.35))
        self.page.insert_text((x, self.y + 11), value, fontsize=9,
                              fontname=PLAIN)

    def paragraph(self, text: str, size: float = 8.2, leading: float = 12.0,
                  width: float = None) -> None:
        width = width or (RIGHT - MARGIN)
        words, line = text.split(), ""
        for word in words:
            trial = f"{line} {word}".strip()
            if pymupdf.get_text_length(trial, fontname=PLAIN, fontsize=size) > width:
                self.space(leading)
                self.page.insert_text((MARGIN, self.y), line, fontsize=size,
                                      fontname=PLAIN)
                self.y += leading
                line = word
            else:
                line = trial
        if line:
            self.space(leading)
            self.page.insert_text((MARGIN, self.y), line, fontsize=size,
                                  fontname=PLAIN)
            self.y += leading

    def party(self, heading: str, lines: list[str], x: float) -> None:
        self.page.insert_text((x, self.y), heading, fontsize=7.5,
                              fontname=BOLD, color=(0.35, 0.35, 0.35))
        for i, line in enumerate(lines):
            self.page.insert_text((x, self.y + 13 + i * 12), line,
                                  fontsize=8.4, fontname=PLAIN)

    # -- pictures -----------------------------------------------------------
    def watermark(self, text: str) -> None:
        """Printed across the page, as a status stamp is."""
        self.page.insert_text(
            (140, 470), text, fontsize=52, fontname=BOLD,
            color=(0.90, 0.90, 0.92), rotate=0,
        )

    def sign(self, name: str, role: str, seed: int) -> None:
        self.space(96)
        self.page.insert_image(
            pymupdf.Rect(MARGIN, self.y, MARGIN + 130, self.y + 45),
            pixmap=signature(seed),
        )
        self.page.draw_line((MARGIN, self.y + 48), (MARGIN + 170, self.y + 48),
                            color=(0.5, 0.5, 0.5), width=0.6)
        self.page.insert_text((MARGIN, self.y + 60), name, fontsize=8,
                              fontname=BOLD)
        self.page.insert_text((MARGIN, self.y + 71), role, fontsize=7.5,
                              fontname=PLAIN, color=(0.4, 0.4, 0.4))
        self.y += 88

    def approval_stamp(self, x: float, y: float, rows: tuple[str, ...]) -> None:
        self.page.insert_image(
            pymupdf.Rect(x, y, x + 118, y + 65), pixmap=stamp(rows)
        )
        for i, row in enumerate(rows[:3]):
            self.page.insert_text((x + 14, y + 20 + i * 13), row,
                                  fontsize=6.4, fontname=PLAIN,
                                  color=(0.55, 0.12, 0.12))

    # -- close --------------------------------------------------------------
    def finish(self, path: Path, footer: str) -> Path:
        total = self.doc.page_count
        for i, page in enumerate(self.doc, start=1):
            page.draw_line((MARGIN, PAGE.height - 74),
                           (RIGHT, PAGE.height - 74),
                           color=(0.82, 0.82, 0.82), width=0.6)
            page.insert_text((MARGIN, PAGE.height - 60), footer, fontsize=7,
                             fontname=PLAIN, color=(0.45, 0.45, 0.45))
            page.insert_text((MARGIN, PAGE.height - 50),
                             "Synthetic test data. Not a real commercial document.",
                             fontsize=7, fontname=PLAIN, color=(0.55, 0.55, 0.55))
            page.insert_text((RIGHT - 60, PAGE.height - 60),
                             f"Page {i} of {total}", fontsize=7,
                             fontname=PLAIN, color=(0.45, 0.45, 0.45))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(path)
        self.doc.close()
        return path


# ---------------------------------------------------------------------------
def money(value: float) -> str:
    return f"{value:,.2f}"


COLUMNS = [
    ("LN", MARGIN, "left"),
    ("DESCRIPTION", 82, "left"),
    ("UOM", 272, "left"),
    ("QTY", 313, "left"),
    ("UNIT PRICE", 352, "right"),
    ("NET", 439, "right"),
    ("VAT%", 457, "left"),
    ("LINE TOTAL", 494, "right"),
]

RIGHT_EDGE = {"UNIT PRICE": 404, "NET": 453, "LINE TOTAL": 536}


def table_header(sheet: Sheet) -> None:
    """The column headings. Reprinted after every page break, as documents do."""
    for name, x, _align in COLUMNS:
        sheet.page.insert_text((x, sheet.y), name, fontsize=7.2, fontname=BOLD)
    sheet.page.draw_line((MARGIN, sheet.y + 4), (RIGHT, sheet.y + 4),
                         color=(0.7, 0.7, 0.7), width=0.6)
    sheet.y += 25


def table_row(sheet: Sheet, line: dict) -> None:
    p = sheet.page
    p.insert_text((MARGIN, sheet.y), str(line["ln"]), fontsize=8.4, fontname=PLAIN)
    p.insert_text((82, sheet.y), line["description"], fontsize=8.4, fontname=PLAIN)
    p.insert_text((272, sheet.y), line["uom"], fontsize=8.4, fontname=PLAIN)
    p.insert_text((324, sheet.y), str(line["qty"]), fontsize=8.4, fontname=PLAIN)

    for key, column in (("unit_price", "UNIT PRICE"), ("net", "NET"),
                        ("total", "LINE TOTAL")):
        text = money(line[key])
        width = pymupdf.get_text_length(text, fontname=PLAIN, fontsize=8.4)
        p.insert_text((RIGHT_EDGE[column] - width, sheet.y), text,
                      fontsize=8.4, fontname=PLAIN)

    p.insert_text((470, sheet.y), str(line["vat"]), fontsize=8.4, fontname=PLAIN)
    sheet.y += 18.4


def totals_block(sheet: Sheet, subtotal: float, vat: float, grand: float,
                 currency: str = "EUR") -> None:
    sheet.space(70)
    sheet.gap(16)
    p = sheet.page

    for label, amount, size, font in (
        ("Subtotal", subtotal, 8.6, PLAIN),
        ("VAT total", vat, 8.6, PLAIN),
    ):
        width = pymupdf.get_text_length(money(amount), fontname=font, fontsize=size)
        p.insert_text((435, sheet.y), label, fontsize=size, fontname=font)
        p.insert_text((540 - width, sheet.y), money(amount), fontsize=size,
                      fontname=font)
        sheet.y += 17

    text = money(grand)
    width = pymupdf.get_text_length(text, fontname=BOLD, fontsize=10)
    p.insert_text((410, sheet.y), f"TOTAL DUE {currency}", fontsize=10,
                  fontname=BOLD)
    p.insert_text((540 - width, sheet.y), text, fontsize=10, fontname=BOLD)
    sheet.y += 24


# ---------------------------------------------------------------------------
def build_lines(spec: list[tuple]) -> list[dict]:
    """Turn a compact specification into priced lines that agree with it."""
    lines = []
    for i, (description, uom, qty, price, vat) in enumerate(spec, start=1):
        net = round(qty * price, 2)
        total = round(net * (1 + vat / 100), 2)
        lines.append({
            "ln": i, "description": description, "uom": uom, "qty": qty,
            "unit_price": price, "net": net, "vat": vat, "total": total,
        })
    return lines


CATALOGUE = [
    ("RRU 4415 radio unit", "EA", 1250.00),
    ("Fibre trunk cable 500m", "EA", 1250.00),
    ("Installation services", "HR", 95.00),
    ("Site survey", "DAY", 640.00),
    ("Antenna mount bracket", "EA", 78.50),
    ("Baseband module BB6630", "EA", 3180.00),
    ("Microwave link 80GHz", "EA", 4120.00),
    ("Power distribution unit", "EA", 890.00),
    ("Cabinet thermal kit", "EA", 445.00),
    ("Commissioning and test", "DAY", 720.00),
    ("Tower climb crew", "DAY", 1180.00),
    ("Spare parts kit A", "EA", 336.00),
    ("Optical patch panel", "EA", 214.00),
    ("Grounding kit", "EA", 96.50),
    ("Remote monitoring licence", "YR", 1540.00),
]


def catalogue_lines(count: int, start: int = 0, vat: float = 24.0) -> list[dict]:
    spec = []
    for i in range(count):
        description, uom, price = CATALOGUE[(start + i) % len(CATALOGUE)]
        qty = 2 + ((start + i * 3) % 9)
        spec.append((description, uom, qty, price, vat))
    return build_lines(spec)
