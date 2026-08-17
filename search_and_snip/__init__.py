"""Search and snip — standalone PDF locate-and-crop tool."""

from .snipper import Document, Hit, NoTextLayer, find_pdfs

__all__ = ["Document", "Hit", "NoTextLayer", "find_pdfs"]
