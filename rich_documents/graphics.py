"""Pictures for the sample documents.

Real documents are not only text. They carry a logo, a scanned signature, an
approval stamp, and drawings — a delivery route, an escalation chain. Those
elements sit on the page alongside the figures an auditor needs to read, and a
reader has to find the figures anyway.

Raster images here are built pixel by pixel rather than loaded from files, so
the sample set has no binary assets to carry around and no image library to
install. They are genuine embedded raster images once placed on a page.
"""

from __future__ import annotations

import math

import pymupdf

WHITE = (255, 255, 255)
INK = (32, 32, 32)
GREY = (140, 140, 140)
RED = (176, 32, 32)
BLUE = (28, 74, 138)


class Raster:
    """A small RGB canvas that can be embedded in a page as an image."""

    def __init__(self, width: int, height: int, fill=WHITE):
        self.width, self.height = width, height
        self.samples = bytearray(bytes(fill) * (width * height))

    def _set(self, x: int, y: int, colour) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 3
            self.samples[i:i + 3] = bytes(colour)

    def dot(self, x: float, y: float, colour, weight: float = 1.0) -> None:
        r = max(1, int(weight))
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    self._set(int(x) + dx, int(y) + dy, colour)

    def line(self, x0, y0, x1, y1, colour, weight: float = 1.0) -> None:
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(steps + 1):
            t = i / steps
            self.dot(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, colour, weight)

    def box(self, x0, y0, x1, y1, colour) -> None:
        for y in range(int(y0), int(y1)):
            for x in range(int(x0), int(x1)):
                self._set(x, y, colour)

    def ring(self, cx, cy, radius, colour, weight: float = 2.0) -> None:
        steps = int(radius * 8) + 8
        for i in range(steps):
            a = 2 * math.pi * i / steps
            self.dot(cx + radius * math.cos(a),
                     cy + radius * math.sin(a), colour, weight)

    def pixmap(self) -> pymupdf.Pixmap:
        return pymupdf.Pixmap(
            pymupdf.csRGB, self.width, self.height, bytes(self.samples), False
        )


def logo(seed: int = 0) -> pymupdf.Pixmap:
    """A supplier mark. Blocks and a ring — enough to be a real image."""
    r = Raster(120, 120)
    r.box(10, 10, 52, 52, BLUE)
    r.box(58, 10, 110, 34, (90, 140, 200))
    r.box(10, 58, 34, 110, (90, 140, 200))
    r.ring(78, 82, 26, BLUE, 3)
    for i in range(4):
        r.line(44 + i * 3, 110, 110, 44 + i * 3, (200, 214, 232), 1)
    _ = seed
    return r.pixmap()


def signature(seed: int = 0) -> pymupdf.Pixmap:
    """A handwritten stroke, of the kind that arrives as a scan."""
    r = Raster(260, 90)
    x, y = 18.0, 58.0
    for i in range(240):
        t = i / 240
        nx = 18 + t * 224
        ny = 58 - 26 * math.sin(t * 7.5 + seed) * (1 - t * 0.45) \
             - 10 * math.sin(t * 2.1 + seed * 2)
        r.line(x, y, nx, ny, INK, 1.4)
        x, y = nx, ny
    r.line(24, 74, 210, 71, INK, 1)
    return r.pixmap()


def stamp(text_rows: tuple[str, ...] = ()) -> pymupdf.Pixmap:
    """An approval stamp: a ruled box, as a rubber stamp prints."""
    r = Raster(200, 110, fill=(252, 248, 248))
    for w in range(3):
        r.line(6 + w, 6, 194 - w, 6, RED, 1)
        r.line(6 + w, 104, 194 - w, 104, RED, 1)
        r.line(6, 6 + w, 6, 104 - w, RED, 1)
        r.line(194, 6 + w, 194, 104 - w, RED, 1)
    for i, _ in enumerate(text_rows[:3]):
        r.line(22, 34 + i * 22, 178, 34 + i * 22, (226, 170, 170), 2)
    r.ring(100, 55, 34, (232, 190, 190), 2)
    return r.pixmap()


def scan_of(page: pymupdf.Page) -> pymupdf.Pixmap:
    """Rasterise a page — the text layer is lost, as in a real scan."""
    return page.get_pixmap(dpi=110)


# ---------------------------------------------------------------------------
# Vector diagrams. Drawn, not typed — a reader must step over them.

def flow_diagram(page: pymupdf.Page, rect: pymupdf.Rect,
                 stages: tuple[str, ...], caption: str) -> None:
    """Boxes joined by arrows, as a process drawing on a document."""
    n = len(stages)
    gap = 14
    width = (rect.width - gap * (n - 1)) / n
    height = min(46, rect.height - 26)

    for i, label in enumerate(stages):
        x0 = rect.x0 + i * (width + gap)
        box = pymupdf.Rect(x0, rect.y0, x0 + width, rect.y0 + height)
        page.draw_rect(box, color=(0.11, 0.29, 0.54), width=0.9,
                       fill=(0.94, 0.96, 0.99), radius=0.12)
        page.insert_textbox(box + (4, 10, -4, -4), label, fontsize=7.5,
                            fontname="helv", align=1, color=(0.11, 0.29, 0.54))
        if i < n - 1:
            y = rect.y0 + height / 2
            page.draw_line((x0 + width + 2, y), (x0 + width + gap - 4, y),
                           color=(0.4, 0.4, 0.4), width=0.8)
            page.draw_line((x0 + width + gap - 8, y - 3),
                           (x0 + width + gap - 4, y),
                           color=(0.4, 0.4, 0.4), width=0.8)
            page.draw_line((x0 + width + gap - 8, y + 3),
                           (x0 + width + gap - 4, y),
                           color=(0.4, 0.4, 0.4), width=0.8)

    page.insert_text((rect.x0, rect.y0 + height + 13), caption,
                     fontsize=7, fontname="helv", color=(0.45, 0.45, 0.45))


def site_plan(page: pymupdf.Page, rect: pymupdf.Rect) -> None:
    """A delivery layout sketch of the kind attached to a purchase order."""
    page.draw_rect(rect, color=(0.6, 0.6, 0.6), width=0.7)

    for i in range(1, 6):
        x = rect.x0 + rect.width * i / 6
        page.draw_line((x, rect.y0), (x, rect.y1),
                       color=(0.91, 0.91, 0.91), width=0.4)

    mast = pymupdf.Rect(rect.x0 + 26, rect.y0 + 20, rect.x0 + 78, rect.y1 - 22)
    page.draw_rect(mast, color=(0.11, 0.29, 0.54), width=0.9)
    page.insert_textbox(mast + (2, 12, -2, -2), "MAST\nA1", fontsize=6.5,
                        fontname="helv", align=1)

    cabin = pymupdf.Rect(rect.x1 - 108, rect.y0 + 30, rect.x1 - 34, rect.y1 - 28)
    page.draw_rect(cabin, color=(0.11, 0.29, 0.54), width=0.9)
    page.insert_textbox(cabin + (2, 10, -2, -2), "EQUIPMENT\nCABIN",
                        fontsize=6.5, fontname="helv", align=1)

    page.draw_line((mast.x1, (mast.y0 + mast.y1) / 2),
                   (cabin.x0, (cabin.y0 + cabin.y1) / 2),
                   color=(0.69, 0.13, 0.13), width=1.1, dashes="[3 2] 0")
    page.insert_text((mast.x1 + 12, (mast.y0 + mast.y1) / 2 - 5),
                     "fibre trunk run", fontsize=6.5, fontname="helv",
                     color=(0.55, 0.12, 0.12))


def escalation_chart(page: pymupdf.Page, rect: pymupdf.Rect) -> None:
    """A two-level chart, as printed in a governance schedule."""
    top = pymupdf.Rect(rect.x0 + rect.width / 2 - 62, rect.y0,
                       rect.x0 + rect.width / 2 + 62, rect.y0 + 30)
    page.draw_rect(top, color=(0.11, 0.29, 0.54), width=0.9,
                   fill=(0.94, 0.96, 0.99))
    page.insert_textbox(top + (3, 9, -3, -3), "Steering committee",
                        fontsize=7.5, fontname="helv", align=1)

    labels = ("Commercial lead", "Delivery manager", "Site supervisor")
    width = (rect.width - 24) / 3
    for i, label in enumerate(labels):
        x0 = rect.x0 + i * (width + 12)
        box = pymupdf.Rect(x0, rect.y0 + 66, x0 + width, rect.y0 + 96)
        page.draw_rect(box, color=(0.45, 0.45, 0.45), width=0.7)
        page.insert_textbox(box + (3, 9, -3, -3), label, fontsize=7,
                            fontname="helv", align=1)
        mid = (box.x0 + box.x1) / 2
        page.draw_line((mid, rect.y0 + 48), (mid, box.y0),
                       color=(0.6, 0.6, 0.6), width=0.7)

    page.draw_line(((top.x0 + top.x1) / 2, top.y1),
                   ((top.x0 + top.x1) / 2, rect.y0 + 48),
                   color=(0.6, 0.6, 0.6), width=0.7)
    page.draw_line((rect.x0 + width / 2, rect.y0 + 48),
                   (rect.x1 - width / 2, rect.y0 + 48),
                   color=(0.6, 0.6, 0.6), width=0.7)
