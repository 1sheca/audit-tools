"""Search and snip.

A standalone tool. Given a PDF, it finds text on the page, returns where that
text sits, and crops that region to an image.

This is what turns a stated figure into showable evidence. An auditor reading
"unit price 1,400.00 exceeds the contracted maximum" has to take it on trust.
An auditor looking at a cropped image of that line on the original invoice does
not.

    from search_and_snip import Document

    doc = Document("data/pdf/INV-2026-1005.pdf")
    hits = doc.search("1,400.00")
    doc.snip(hits[0], "out/price.png")

Also supports regular expressions, label-anchored lookup (read the value that
sits beside or beneath a label), and snipping a whole table row rather than a
single word.

Requires a text layer. A scanned or photographed document has no text to search
and returns nothing — that is a real limitation of the deterministic route, not
a defect, and it is why a cloud extraction service exists for image documents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import pymupdf

__all__ = ["Hit", "Document", "NoTextLayer"]

DEFAULT_PADDING = 4.0
# Vertical padding is tighter than horizontal. Table rows sit only a few points
# apart, and a generous vertical margin pulls a sliver of the neighbouring row
# into the crop — which looks like carelessness in a working paper.
DEFAULT_VERTICAL_PADDING = 1.5
DEFAULT_ZOOM = 2.5
ROW_TOLERANCE = 3.0


class NoTextLayer(RuntimeError):
    """The PDF carries no extractable text.

    Almost always a scan or a photograph. Deterministic search cannot operate
    on it and a cloud extraction service is required instead.
    """


@dataclass(frozen=True)
class Hit:
    """A located piece of text and the rectangle it occupies."""

    text: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def describe(self) -> str:
        return (f"page {self.page}  '{self.text}'  "
                f"[{self.x0:.0f},{self.y0:.0f} {self.x1:.0f},{self.y1:.0f}]")


class Document:
    """A PDF opened for searching and cropping."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self._doc = pymupdf.open(self.path)
        if not any(page.get_text().strip() for page in self._doc):
            raise NoTextLayer(
                f"{self.path.name} has no text layer. Deterministic search "
                f"cannot read it; a cloud extraction service is required."
            )

    def __enter__(self) -> "Document":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._doc.close()

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def text(self, page: int = 0) -> str:
        return self._doc[page].get_text()

    # -- searching --------------------------------------------------------
    def search(self, needle: str, page: Optional[int] = None) -> list[Hit]:
        """Find literal text. Searches every page unless one is named."""
        hits: list[Hit] = []
        pages = range(self.page_count) if page is None else [page]
        for n in pages:
            for rect in self._doc[n].search_for(needle):
                hits.append(Hit(needle, n, rect.x0, rect.y0, rect.x1, rect.y1))
        return hits

    def search_pattern(self, pattern: str, page: Optional[int] = None) -> list[Hit]:
        """Find text matching a regular expression.

        Useful for locating anything with a known shape rather than a known
        value — invoice references, tax numbers, IBANs, dated fields.
        """
        compiled = re.compile(pattern)
        hits: list[Hit] = []
        pages = range(self.page_count) if page is None else [page]
        for n in pages:
            for word in self._words(n):
                if compiled.search(word["text"]):
                    hits.append(Hit(word["text"], n, word["x0"], word["y0"],
                                    word["x1"], word["y1"]))
        return hits

    def value_beside(self, label: str, page: int = 0,
                     direction: str = "below") -> Optional[Hit]:
        """Read the value printed beneath or to the right of a label.

        Documents put labels and values in a fixed spatial relationship rather
        than in a machine-readable structure, which is why this is positional
        rather than a text lookup.
        """
        anchors = self.search(label, page=page)
        if not anchors:
            return None
        anchor = anchors[0]
        words = self._words(page)

        if direction == "below":
            candidates = [
                w for w in words
                if w["y0"] > anchor.y1 and abs(w["x0"] - anchor.x0) < 26
                and w["y0"] - anchor.y1 < 22
            ]
        else:
            candidates = [
                w for w in words
                if w["x0"] > anchor.x1 and abs(w["y0"] - anchor.y0) < ROW_TOLERANCE
            ]
        if not candidates:
            return None

        key = (lambda w: (w["y0"], w["x0"])) if direction == "below" else (lambda w: w["x0"])
        first = min(candidates, key=key)
        group = [
            w for w in candidates
            if abs(w["y0"] - first["y0"]) < ROW_TOLERANCE
            and w["x0"] - first["x0"] < 140
        ]
        group.sort(key=lambda w: w["x0"])
        return Hit(
            " ".join(w["text"] for w in group),
            page,
            min(w["x0"] for w in group),
            min(w["y0"] for w in group),
            max(w["x1"] for w in group),
            max(w["y1"] for w in group),
        )

    def row_containing(self, hit: Hit, margin: float = 8.0) -> Hit:
        """Widen a hit to the full width of the row it sits in.

        A single figure taken out of its row proves little. The row shows the
        description and quantity alongside it, which is what makes the snip
        readable as evidence.
        """
        page = self._doc[hit.page]
        same_row = [
            w for w in self._words(hit.page)
            if abs(w["y0"] - hit.y0) <= ROW_TOLERANCE
        ]
        if not same_row:
            return hit
        return Hit(
            " ".join(w["text"] for w in sorted(same_row, key=lambda w: w["x0"])),
            hit.page,
            max(0.0, min(w["x0"] for w in same_row) - margin),
            min(w["y0"] for w in same_row) - margin,
            min(page.rect.width, max(w["x1"] for w in same_row) + margin),
            max(w["y1"] for w in same_row) + margin,
        )

    # -- cropping ---------------------------------------------------------
    def snip(
        self,
        hit: Hit,
        output: str | Path,
        padding: float = DEFAULT_PADDING,
        zoom: float = DEFAULT_ZOOM,
        highlight: bool = False,
        vertical_padding: float | None = None,
    ) -> Path:
        """Crop the region to a PNG.

        zoom raises the render resolution above the PDF's nominal 72 dpi so the
        result is legible when placed in a working paper.
        """
        if vertical_padding is None:
            vertical_padding = min(padding, DEFAULT_VERTICAL_PADDING)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        page = self._doc[hit.page]
        clip = pymupdf.Rect(
            max(0.0, hit.x0 - padding),
            max(0.0, hit.y0 - vertical_padding),
            min(page.rect.width, hit.x1 + padding),
            min(page.rect.height, hit.y1 + vertical_padding),
        )

        if highlight:
            # Render from a copy so the source file is never modified.
            scratch = pymupdf.open()
            scratch.insert_pdf(self._doc, from_page=hit.page, to_page=hit.page)
            target = scratch[0]
            target.draw_rect(pymupdf.Rect(*hit.rect), color=(0.72, 0.12, 0.15), width=1.1)
            pix = target.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
            scratch.close()
        else:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)

        pix.save(output)
        return output

    def snip_row(self, hit: Hit, output: str | Path, **kwargs) -> Path:
        return self.snip(self.row_containing(hit), output, **kwargs)

    # -- internals --------------------------------------------------------
    def _words(self, page: int) -> list[dict]:
        return [
            {"text": w[4], "x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3]}
            for w in self._doc[page].get_text("words")
        ]


def find_pdfs(directory: str | Path = None) -> Iterator[Path]:
    directory = Path(directory or Path(__file__).resolve().parent.parent / "data" / "pdf")
    return sorted(directory.glob("*.pdf"))
