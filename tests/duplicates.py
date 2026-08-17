"""Documents that contain the same row twice, for two different reasons.

`overlay_text_layer` reproduces what a scanned-then-OCR'd document looks like:
a second, invisible copy of the text sitting exactly beneath the visible text.
Every word extracts twice. Nothing was billed twice.

`repeat_line_elsewhere` reproduces a genuine duplicate: the same billed line
printed a second time further down the table, as a real invoice would show it
if the line had been entered twice.

The two must not be treated the same way. The first is noise. The second is a
finding.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf


def overlay_text_layer(source: str | Path, target: str | Path) -> Path:
    """Copy the page onto itself, so all its text extracts twice."""
    source, target = Path(source), Path(target)
    with pymupdf.open(source) as original:
        out = pymupdf.open()
        page = out.new_page(width=original[0].rect.width,
                            height=original[0].rect.height)
        # The same page drawn twice at the same coordinates.
        page.show_pdf_page(page.rect, original, 0)
        page.show_pdf_page(page.rect, original, 0)
        target.parent.mkdir(parents=True, exist_ok=True)
        out.save(target)
        out.close()
    return target


def repeat_line_elsewhere(source: str | Path, target: str | Path,
                          line_number: int) -> Path:
    """Print an existing billed line a second time, lower down the table.

    The copy is placed in the gap beneath the last line of the table, at the
    same column positions, so it reads as an ordinary further row rather than
    as a rendering artefact.
    """
    source, target = Path(source), Path(target)
    with pymupdf.open(source) as original:
        page = original[0]
        words = page.get_text("words")

        row = [w for w in words if w[4].strip() == str(line_number)]
        if not row:
            raise ValueError(f"line {line_number} not found")
        y0 = row[0][1]
        source_row = [w for w in words if abs(w[1] - y0) <= 3.0]

        table_rows = sorted({
            round(w[1], 1) for w in words
            if w[0] < 60 and w[4].strip().isdigit()
        })
        spacing = table_rows[1] - table_rows[0] if len(table_rows) > 1 else 18.4
        drop = (table_rows[-1] + spacing) - y0

        out = pymupdf.open()
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.show_pdf_page(new_page.rect, original, 0)

        for w in source_row:
            new_page.insert_text(
                (w[0], w[3] + drop), w[4],
                fontname="helv", fontsize=9,
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        out.save(target)
        out.close()
    return target
