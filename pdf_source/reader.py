"""PDF reader.

Parses invoices, purchase orders and contracts from PDF into structured values,
and records where on the page every value was found.

This module exists because two of the tools need the same thing from a PDF and
should not each grow their own copy of it. The three tools remain independent of
one another; both `sum_finding` and `evidence_generator` depend on this reader in
the same way they depend on pymupdf.

The output is a pair: the parsed document, and a map from field path to page
position. The positions are the reason this is worth doing properly — they are
what allows an evidence citation to be cropped from the original page rather
than merely asserted.

    from pdf_source import read_document

    document, positions = read_document("data/pdf/INV-2026-1005.pdf")
    document["lines"][0]["unit_price"]      # 1400.0
    positions["lines[0].unit_price"]        # Position(page=0, x0=..., ...)

Requires a text layer. A scan raises NoTextLayer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pymupdf

__all__ = ["Position", "NoTextLayer", "UnknownDocumentType", "read_document", "read_all"]

ROW_TOLERANCE = 3.0
LABEL_GAP = 24.0        # a value sits within this distance below its label
COLUMN_DRIFT = 30.0     # and within this horizontal distance of it
PARTY_COLUMN = 150.0    # width of a party block, short of any adjacent column
NUMERIC = re.compile(r"^-?[\d,]+\.?\d*$")


class NoTextLayer(RuntimeError):
    """The PDF carries no extractable text — almost always a scan."""


class UnknownDocumentType(ValueError):
    """The page does not match any layout this reader understands."""


@dataclass(frozen=True)
class Position:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    def describe(self) -> str:
        return f"p{self.page + 1} [{self.x0:.0f},{self.y0:.0f}]"


CURRENCY_PREFIX = re.compile(
    r"^(?:EUR|USD|GBP|SEK|NOK|DKK|CHF|INR|[€$£₹])\s*(?=[\d(-])", re.I
)


def _strip_currency(text: str) -> str:
    """Remove a currency code printed hard against its amount.

    Documents set the currency and the figure so close that they extract as a
    single token — "EUR100,234.40". The figure is still the figure.
    """
    return CURRENCY_PREFIX.sub("", text.strip())


def _number(text: str) -> Optional[float]:
    """Parse a printed figure. Returns None where characters do not resolve."""
    text = _strip_currency(text)
    cleaned = text.replace(",", "").strip()
    if not NUMERIC.match(text.strip()):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_number(text: str) -> bool:
    return bool(NUMERIC.match(_strip_currency(text)))


def _box(words: list[dict], page: Optional[int] = None) -> Position:
    """Bounding box of a word group.

    The page is taken from the words themselves. A group never spans two
    pages: rows are built per page and never merged across a page break, so
    every word in a group shares one page number.
    """
    if page is None:
        page = words[0]["page"]
    return Position(
        page,
        min(w["x0"] for w in words),
        min(w["y0"] for w in words),
        max(w["x1"] for w in words),
        max(w["y1"] for w in words),
    )


# ---------------------------------------------------------------------------
class _Page:
    """A page reduced to positioned words grouped into rows."""

    def __init__(self, page, index: int):
        self.index = index
        raw = [
            {"text": w[4], "x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3],
             "page": index}
            for w in page.get_text("words")
        ]

        # A word printed twice at the same coordinates is one word extracted
        # twice, not two words. This happens when a document carries more than
        # one text layer — usually a scan that has been through OCR, leaving
        # invisible text beneath the visible text. Both copies extract.
        #
        # Position is what makes this safe. Two glyphs cannot occupy the same
        # point on the page and mean different things. A line genuinely billed
        # twice is printed somewhere else, and is untouched by this.
        self.words = []
        self.duplicate_words = 0
        seen: set[tuple] = set()
        for word in raw:
            key = (word["text"], round(word["x0"], 1), round(word["y0"], 1))
            if key in seen:
                self.duplicate_words += 1
                continue
            seen.add(key)
            self.words.append(word)
        self.rows: list[list[dict]] = []
        for word in sorted(self.words, key=lambda w: (round(w["y0"], 1), w["x0"])):
            if self.rows and abs(self.rows[-1][0]["y0"] - word["y0"]) <= ROW_TOLERANCE:
                self.rows[-1].append(word)
            else:
                self.rows.append([word])
        for row in self.rows:
            row.sort(key=lambda w: w["x0"])

    @staticmethod
    def text_of(row: list[dict]) -> str:
        return " ".join(w["text"] for w in row)

    @property
    def text(self) -> str:
        return "\n".join(self.text_of(r) for r in self.rows)

    def row_index(self, *needles: str) -> Optional[int]:
        for i, row in enumerate(self.rows):
            haystack = self.text_of(row).lower()
            if all(n.lower() in haystack for n in needles):
                return i
        return None

    def below_label(self, label: str) -> tuple[Optional[str], Optional[Position]]:
        """Read the value printed beneath a label, left-aligned to it."""
        parts = label.split()
        idx = self.row_index(*parts)
        if idx is None:
            return None, None

        anchor = next(
            (w["x0"] for w in self.rows[idx]
             if w["text"].lower().rstrip(":") == parts[0].lower()),
            None,
        )
        if anchor is None:
            return None, None

        # A value printed under a label is on the same page as the label. Rows
        # from the next page must not be read as its continuation.
        label_page = self.rows[idx][0]["page"]
        label_top = self.rows[idx][0]["y0"]
        label_bottom = self.rows[idx][0]["y1"]

        # The value must start lower down the page than the label starts. It
        # need not clear the label's descender: where a document sets a label
        # tightly above its value the two boxes overlap by a point or so, and
        # that is still a label above a value. Requiring a clear gap loses the
        # field entirely on documents that set text tightly.
        candidates = [
            w for r in self.rows[idx + 1: idx + 3] for w in r
            if w["page"] == label_page
            and abs(w["x0"] - anchor) <= COLUMN_DRIFT
            and w["y0"] > label_top + 3.0
            and w["y0"] - label_bottom < LABEL_GAP
        ]
        if not candidates:
            return None, None

        first = min(candidates, key=lambda w: (w["y0"], w["x0"]))
        group = [first]
        for word in self.rows[self._row_of(first)]:
            if word is first or word["x0"] <= first["x0"]:
                continue
            if word["x0"] - (group[-1]["x0"] + (group[-1]["x1"] - group[-1]["x0"])) > 12:
                break
            group.append(word)

        return " ".join(w["text"] for w in group), _box(group)

    def _row_of(self, word: dict) -> int:
        for i, row in enumerate(self.rows):
            if word in row:
                return i
        return 0


class _Document(_Page):
    """Every page of a PDF, read as one continuous sequence of rows.

    Rows are built per page and then concatenated in page order. They are
    never merged across a page break, so two lines that happen to sit at the
    same height on different pages stay separate. Every word carries its own
    page number, so a value found on page 3 is cited against page 3.

    This is what allows a table or a party block to continue past the foot of
    one page onto the next, which is normal in real documents.
    """

    def __init__(self, pdf):
        self.pages = [_Page(page, i) for i, page in enumerate(pdf)]
        self.index = 0
        self.duplicate_words = sum(p.duplicate_words for p in self.pages)
        self.words = [w for p in self.pages for w in p.words]

        self.page_height = pdf[0].rect.height if len(pdf) else 0.0
        self.furniture = self._furniture()
        self.rows = [
            row for p in self.pages for row in p.rows
            if id(row) not in self.furniture
        ]

    def _furniture(self) -> set[int]:
        """Rows that are page furniture rather than content.

        A running header or footer is recognised by what it does, not by
        guessing where the margin is: it is printed at the same height on more
        than one page, in the top or bottom band of the page, with the same
        wording apart from the page number.

        This matters because a footer sitting under a table is otherwise read
        as one more row of that table. A page number becomes a figure, and a
        strapline becomes a description.

        A single-page document has nothing to compare against, so nothing is
        treated as furniture.
        """
        if len(self.pages) < 2:
            return set()

        band = self.page_height * 0.12
        seen: dict[tuple, list[list[dict]]] = {}

        for page in self.pages:
            for row in page.rows:
                top = row[0]["y0"]
                if band < top < self.page_height - band:
                    continue
                shape = (
                    round(top, 0),
                    re.sub(r"\d+", "#", self.text_of(row)),
                )
                seen.setdefault(shape, []).append(row)

        return {
            id(row)
            for rows in seen.values() if len(rows) > 1
            for row in rows
        }

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def header_text(self) -> str:
        """The top of each page, joined. Used only to identify the layout."""
        return "\n".join(p.text[:400] for p in self.pages).upper()


# ---------------------------------------------------------------------------
def _is_extraction_artefact(record: dict, page: int, y0: float,
                            accepted: list[tuple[dict, int, float]],
                            previous: Optional[tuple[dict, int, float]]
                            ) -> Optional[str]:
    """Decide whether an identical repeated row came from the extraction.

    Two rows with the same content are not necessarily the same row. The
    document may genuinely bill a line twice, which is an audit finding and
    must survive. What separates them is where they are printed.

    An artefact sits in one of two places:

    - the same coordinates on the same page, which is what an overlapping
      text layer produces — common in documents that were scanned and then
      put through OCR, where invisible text sits beneath the visible text;
    - immediately across a page break, where a row on the seam is rendered
      onto both pages.

    A genuine duplicate line sits somewhere else in the table entirely, with
    other rows between it and its twin. Those are kept.

    Returns the reason if the row is an artefact, otherwise None.
    """
    for earlier, earlier_page, earlier_y0 in accepted:
        if earlier != record:
            continue
        if earlier_page == page and abs(earlier_y0 - y0) <= ROW_TOLERANCE * 2:
            return "same row printed twice at the same position"

    if previous is not None:
        earlier, earlier_page, _ = previous
        if earlier == record and page - earlier_page == 1:
            return "row on a page break, rendered onto both pages"

    return None


def _read_table(page: _Page, header: tuple[str, ...], stop: re.Pattern,
                prefix: str, positions: dict[str, Position],
                removed: Optional[list[dict]] = None) -> list[dict]:
    """Read a line table, recording the position of each figure it contains."""
    start = page.row_index(*header)
    if start is None:
        return []

    columns = {w["text"].upper().rstrip("%"): w["x1"] for w in page.rows[start]}

    # Where the figure columns begin. A number printed to the left of this is
    # part of the description — a part number, a model, a capacity — not a
    # figure in a column. Dropping it silently shortens the description, and
    # a part number is often the only thing telling two similar lines apart.
    figure_headers = ("QTY", "ORDERED", "UNIT", "PRICE", "NET", "VAT",
                      "LINE", "TOTAL", "UOM")
    figure_zone = min(
        [w["x0"] for w in page.rows[start]
         if w["text"].upper().rstrip("%") in figure_headers],
        default=0.0,
    )
    lines: list[dict] = []
    placed: list[tuple[dict, int, float]] = []
    previous: Optional[tuple[dict, int, float]] = None

    for row in page.rows[start + 1:]:
        text = page.text_of(row)
        if stop.search(text):
            break
        if not row or not row[0]["text"].strip().lstrip("0").isdigit():
            if not (row and row[0]["text"].strip().isdigit()):
                continue

        line_number = int(row[0]["text"])
        ref = f"{prefix}[{len(lines)}]"

        figures = [
            w for w in row[1:]
            if _is_number(w["text"]) and w["x0"] >= figure_zone - COLUMN_DRIFT
        ]
        words = [w for w in row[1:] if w not in figures]

        record: dict[str, Any] = {"line_number": line_number}

        # Description is the leading words; unit of measure the trailing token
        # where the header declared one.
        if words:
            if "UOM" in columns and len(words) > 1:
                record["description"] = " ".join(w["text"] for w in words[:-1])
                record["unit_of_measure"] = words[-1]["text"]
                positions[f"{ref}.unit_of_measure"] = _box([words[-1]])
            else:
                record["description"] = " ".join(w["text"] for w in words)
            positions[f"{ref}.description"] = _box(words)

        # Figures are assigned to the column they fall under. The assignment is
        # made across the whole row at once, closest pair first, rather than
        # letting each figure take the nearest free column in turn. A figure
        # set slightly wide of its own column can otherwise sit closer to its
        # neighbour and take it, pushing every figure after it one column
        # along — silently, and with plausible-looking numbers.
        wanted = [
            ("quantity", ("QTY", "ORDERED")),
            ("unit_price", ("UNIT PRICE", "PRICE", "NET PRICE")),
            ("net_amount", ("NET", "NET VALUE")),
            ("tax_rate", ("VAT",)),
            ("line_total", ("LINE TOTAL", "TOTAL")),
        ]

        pairs = []
        for figure in figures:
            for name, header_names in wanted:
                for header_name in header_names:
                    if header_name not in columns:
                        continue
                    distance = abs(columns[header_name] - figure["x1"])
                    if distance < 40:
                        pairs.append((distance, id(figure), name, figure))

        taken_columns: set[str] = set()
        taken_figures: set[int] = set()
        for _distance, marker, name, figure in sorted(pairs, key=lambda p: p[0]):
            if name in taken_columns or marker in taken_figures:
                continue
            value = _number(figure["text"])
            if value is None:
                continue
            taken_columns.add(name)
            taken_figures.add(marker)
            record[name] = value
            positions[f"{ref}.{name}"] = _box([figure])

        if "tax_rate" in record and "net_amount" in record and "tax_amount" not in record:
            # The document prints the rate and the line total but not the tax
            # amount itself; derive it so the arithmetic checks have a subject.
            if "line_total" in record:
                record["tax_amount"] = round(record["line_total"] - record["net_amount"], 2)

        if "quantity" in record and "unit_price" in record:
            row_page, row_y0 = row[0]["page"], row[0]["y0"]

            reason = _is_extraction_artefact(
                record, row_page, row_y0, placed, previous
            )
            if reason is not None:
                # Discard the repeat, but never without a record of it.
                if removed is not None:
                    removed.append({
                        "line_number": record.get("line_number"),
                        "description": record.get("description"),
                        "page": row_page + 1,
                        "reason": reason,
                    })
                for key in list(positions):
                    if key.startswith(f"{ref}."):
                        del positions[key]
                continue

            previous = (record, row_page, row_y0)
            placed.append(previous)
            lines.append(record)

    return lines


def _read_totals(page: _Page, positions: dict[str, Position]) -> dict:
    totals: dict[str, float] = {}
    labels = {
        "subtotal": ("SUBTOTAL",),
        "tax_total": ("vat total",),
        "grand_total": ("total due",),
    }
    for key, needles in labels.items():
        idx = page.row_index(*needles)
        if idx is None:
            continue
        figures = [w for w in page.rows[idx] if _is_number(w["text"])]
        if not figures:
            continue
        value = _number(figures[-1]["text"])
        if value is None:
            continue
        totals[key] = value
        positions[f"totals.{key}"] = _box([figures[-1]])
    return totals


def _read_party(page: _Page, label: str, prefix: str,
                positions: dict[str, Position]) -> Optional[dict]:
    """Read a party block — the name and details printed beneath a heading.

    Party identity is not decoration. Whether the vendor named on an invoice is
    the vendor named on the purchase order is itself a three-way match check.
    """
    parts = label.split()
    idx = page.row_index(*parts)
    if idx is None:
        return None

    anchor = next(
        (w["x0"] for w in page.rows[idx]
         if w["text"].upper().rstrip(":") == parts[0].upper()),
        None,
    )
    if anchor is None:
        return None

    party: dict[str, Any] = {}
    label_page = page.rows[idx][0]["page"]
    for row in page.rows[idx + 1: idx + 9]:
        # A party block does not continue onto the next page. Whatever is
        # printed at the top of the following page is a different block.
        if row[0]["page"] != label_page:
            break
        # Only words in this party's column. The band stops short of any
        # adjacent block printed to the right.
        column = [w for w in row if -COLUMN_DRIFT <= w["x0"] - anchor <= PARTY_COLUMN]
        if not column:
            # This row belongs entirely to a neighbouring column. Skip it —
            # the block continues below.
            continue
        text = " ".join(w["text"] for w in column).strip()
        if not text:
            continue

        # A new all-capitals heading ends the block.
        if text.isupper() and len(text.split()) <= 3 and "name" in party:
            break

        if "name" not in party:
            party["name"] = text
            positions[f"{prefix}.name"] = _box(column)
        elif text.lower().startswith("account"):
            party["vendor_id"] = text.split(maxsplit=1)[-1]
            positions[f"{prefix}.vendor_id"] = _box(column)
        elif text.lower().startswith("tax reg"):
            party["tax_registration"] = text.split(".", 1)[-1].strip()
            positions[f"{prefix}.tax_registration"] = _box(column)
        elif "location" not in party:
            party["location"] = text
            positions[f"{prefix}.location"] = _box(column)

    return party or None


# ---------------------------------------------------------------------------
def _read_invoice(page: _Page, positions: dict[str, Position]) -> dict:
    def field(path: str, label: str) -> Optional[str]:
        value, box = page.below_label(label)
        if box is not None:
            positions[path] = box
        return value

    doc: dict[str, Any] = {"document_type": "invoice", "source_system": "SharePoint"}
    doc["seller"] = _read_party(page, "SELLER", "seller", positions)
    doc["buyer"] = _read_party(page, "BILL TO", "buyer", positions)
    doc["document_id"] = field("document_id", "INVOICE NUMBER")
    doc["issue_date"] = field("issue_date", "ISSUE DATE")
    doc["due_date"] = field("due_date", "DUE DATE")
    doc["currency"] = field("currency", "CURRENCY") or "EUR"

    terms = field("payment_terms", "TERMS")
    if terms and terms.lower() != "not stated":
        doc["payment_terms"] = terms

    po = field("po_reference", "PURCHASE ORDER REFERENCE")
    doc["po_reference"] = None if (po and "none" in po.lower()) else po

    removed: list[dict] = []
    doc["lines"] = _read_table(
        page, ("LN", "DESCRIPTION", "QTY"), re.compile(r"subtotal", re.I),
        "lines", positions, removed,
    )
    if removed:
        doc["removed_duplicates"] = removed
    doc["totals"] = _read_totals(page, positions)
    return doc


def _read_purchase_order(page: _Page, positions: dict[str, Position]) -> dict:
    def field(path: str, label: str) -> Optional[str]:
        value, box = page.below_label(label)
        if box is not None:
            positions[path] = box
        return value

    doc: dict[str, Any] = {"document_type": "purchase_order", "source_system": "SAP"}
    doc["vendor"] = _read_party(page, "SUPPLIER", "vendor", positions)
    doc["document_id"] = field("document_id", "PO NUMBER")
    doc["order_date"] = field("order_date", "ORDER DATE")
    doc["delivery_date"] = field("delivery_date", "DELIVERY BY")
    doc["requisition_number"] = field("requisition_number", "REQUISITION")
    doc["currency"] = field("currency", "CURRENCY") or "EUR"
    doc["payment_terms"] = field("payment_terms", "PAYMENT TERMS")

    reference = field("contract_reference", "CONTRACT REFERENCE")
    doc["contract_reference"] = None if (reference and reference.lower() == "none") else reference

    removed: list[dict] = []
    doc["lines"] = _read_table(
        page, ("ITEM", "ORDERED", "NET"), re.compile(r"order value", re.I),
        "lines", positions, removed,
    )
    if removed:
        doc["removed_duplicates"] = removed

    idx = page.row_index("order value")
    if idx is not None:
        figures = [w for w in page.rows[idx] if _is_number(w["text"])]
        if figures:
            value = _number(figures[-1]["text"])
            if value is not None:
                doc["order_value"] = value
                positions["order_value"] = _box([figures[-1]])
    return doc


def _read_contract(page: _Page, positions: dict[str, Position]) -> dict:
    def field(path: str, label: str) -> Optional[str]:
        value, box = page.below_label(label)
        if box is not None:
            positions[path] = box
        return value

    doc: dict[str, Any] = {"document_type": "contract", "source_system": "CLM"}
    doc["counterparty"] = _read_party(page, "COUNTERPARTY", "counterparty", positions)
    doc["document_id"] = field("document_id", "CONTRACT REFERENCE")
    doc["effective_date"] = field("effective_date", "EFFECTIVE DATE")
    doc["expiry_date"] = field("expiry_date", "EXPIRY DATE")
    doc["governing_law"] = field("governing_law", "GOVERNING LAW")

    schedule: list[dict] = []
    start = page.row_index("ITEM DESCRIPTION", "MAXIMUM")
    if start is not None:
        # Same rule as the line tables: a number to the left of the rate
        # columns is part of the item description, not the rate.
        rate_zone = min(
            [w["x0"] for w in page.rows[start]
             if w["text"].upper() in ("UOM", "MAXIMUM", "UNIT", "RATE")],
            default=0.0,
        )
        for row in page.rows[start + 1:]:
            text = page.text_of(row)
            if re.search(r"clause|renewal|synthetic", text, re.I):
                break
            figures = [
                w for w in row
                if _is_number(w["text"]) and w["x0"] >= rate_zone - COLUMN_DRIFT
            ]
            if not figures:
                continue
            rate = _number(figures[-1]["text"])
            if rate is None:
                continue
            words = [w for w in row if w not in figures]
            ref = f"rate_schedule[{len(schedule)}]"
            term = {"max_unit_price": rate}
            if words:
                term["description"] = " ".join(w["text"] for w in words[:-1]) or words[0]["text"]
                term["unit_of_measure"] = words[-1]["text"]
                positions[f"{ref}.description"] = _box(words)
            positions[f"{ref}.max_unit_price"] = _box([figures[-1]])
            schedule.append(term)

    doc["rate_schedule"] = schedule

    # The payment clause is prose, not a labelled field.
    match = re.search(r"settled on (Net \d+) terms", page.text)
    if match:
        doc["payment_terms"] = match.group(1)
    return doc


READERS = {
    "COMMERCIAL INVOICE": _read_invoice,
    "PURCHASE ORDER": _read_purchase_order,
    "MASTER SUPPLY AGREEMENT": _read_contract,
}


def read_document(path: str | Path) -> tuple[dict, dict[str, Position]]:
    """Parse one PDF. Returns the document and a field-path to position map."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    with pymupdf.open(path) as pdf:
        if not any(p.get_text().strip() for p in pdf):
            raise NoTextLayer(
                f"{path.name} has no text layer. Deterministic parsing cannot "
                f"read it; a cloud extraction service is required."
            )
        page = _Document(pdf)

    # The layout marker is looked for at the top of every page, not only the
    # first. A document may open with a covering page, and a page extracted
    # from the middle of a larger file still carries its own heading.
    header = page.header_text()
    for marker, reader in READERS.items():
        if marker in header:
            positions: dict[str, Position] = {}
            document = reader(page, positions)
            document["source_file"] = path.name
            document["page_count"] = page.page_count

            if page.duplicate_words:
                # Recorded, not hidden. If anyone asks whether this tool
                # dropped anything from the document, the answer is a list.
                document.setdefault("removed_duplicates", []).append({
                    "words": page.duplicate_words,
                    "reason": "text printed twice at the same coordinates "
                              "(more than one text layer on the page)",
                })
            return document, positions

    raise UnknownDocumentType(
        f"{path.name}: no recognised layout across {page.page_count} "
        f"page(s). This reader knows invoices, purchase orders and supply "
        f"agreements in the layouts it was built against."
    )


def read_all(directory: str | Path = "data/pdf") -> list[tuple[dict, dict[str, Position]]]:
    """Parse every PDF in a directory, in filename order."""
    return [read_document(p) for p in sorted(Path(directory).glob("*.pdf"))]
