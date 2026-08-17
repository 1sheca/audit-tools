"""Build a multi-page copy of a single-page document, for testing.

A real invoice runs over several pages, with the line table broken by a page
foot and the totals printed on a later page. None of the sample documents do
that, so the multi-page path would otherwise never be exercised.

The split is made by clipping: the top band of the original becomes page one
and the remainder becomes page two. The text is the original text, not a
retyping of it, so what the reader sees is a genuine two-page document whose
figures must still be found and must still add up.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf


def _clean_gap(page, near: float) -> float:
    """The nearest height to `near` at which no word is cut in half.

    A cut through a row prints that row on both pages. No real document does
    that, so a split there would be testing an artefact of the harness rather
    than the behaviour of the reader.
    """
    words = page.get_text("words")
    candidates = sorted(
        {round((w[3] + n[1]) / 2, 1)
         for w in words for n in words
         if n[1] > w[3]},
    )
    clean = [
        y for y in candidates
        if not any(w[1] < y < w[3] for w in words)
    ]
    if not clean:
        raise ValueError("no clean split point on this page")
    return min(clean, key=lambda y: abs(y - near))


def split_across_pages(source: str | Path, target: str | Path,
                       at_height: float) -> Path:
    """Rewrite a one-page PDF as two pages, cut near the given height.

    The cut is moved to the nearest gap between rows, so no row is divided.
    """
    source, target = Path(source), Path(target)
    with pymupdf.open(source) as original:
        page = original[0]
        width, height = page.rect.width, page.rect.height
        at_height = _clean_gap(page, at_height)

        bands = [
            pymupdf.Rect(0, 0, width, at_height),
            pymupdf.Rect(0, at_height, width, height),
        ]

        out = pymupdf.open()
        for band in bands:
            new_page = out.new_page(width=width, height=band.height)
            new_page.show_pdf_page(new_page.rect, original, 0, clip=band)

        target.parent.mkdir(parents=True, exist_ok=True)
        out.save(target)
        out.close()

    return target
