"""Evidence generator.

A standalone tool. Given a source document and the fields a conclusion rests
on, it produces an evidence pack: a structured, citable record of where every
value came from, what it was, and how reliably it was read.

The tool holds no audit logic. It does not decide whether anything is right or
wrong. It records provenance, which is what makes a conclusion defensible after
the fact — an audit finding without traceable evidence cannot go into a file.

    from evidence_generator import EvidenceGenerator

    gen = EvidenceGenerator(document)
    gen.cite("totals.grand_total", confidence=0.94)
    gen.cite("seller.tax_id")
    pack = gen.pack(conclusion="Invoice total agrees to purchase order")

Field paths are dotted and support list indexing: "lines[0].unit_price".
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

__all__ = ["EvidenceItem", "EvidencePack", "EvidenceGenerator", "FieldNotFound"]

_INDEX = re.compile(r"^(?P<name>[^\[\]]+)(?:\[(?P<index>\d+)\])?$")


class FieldNotFound(LookupError):
    """The requested field path does not exist in the document.

    Raised rather than returning None: silently citing a missing value is how
    an evidence pack ends up asserting something the document never said.
    """


# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EvidenceItem:
    """One citable value, with everything needed to find it again."""

    source_system: str
    document_id: str
    document_type: str
    field_path: str
    value: Any
    confidence: Optional[float] = None
    page: Optional[int] = None
    bounding_box: Optional[tuple[float, float, float, float]] = None
    note: Optional[str] = None

    def describe(self) -> str:
        conf = "" if self.confidence is None else f"  (conf {self.confidence:.2f})"
        return f"{self.source_system}/{self.document_id}  {self.field_path} = {self.value}{conf}"


@dataclass
class EvidencePack:
    """A set of evidence items supporting one conclusion."""

    pack_id: str
    created_at: str
    conclusion: Optional[str]
    items: list[EvidenceItem] = field(default_factory=list)
    integrity_hash: Optional[str] = None

    # -- reporting --------------------------------------------------------
    @property
    def sources(self) -> set[str]:
        return {i.source_system for i in self.items}

    @property
    def documents(self) -> list[str]:
        seen: list[str] = []
        for i in self.items:
            if i.document_id not in seen:
                seen.append(i.document_id)
        return seen

    @property
    def weakest_confidence(self) -> Optional[float]:
        """Lowest confidence across cited items.

        A pack is only as reliable as its least reliable citation, so this is
        a minimum rather than an average.
        """
        scored = [i.confidence for i in self.items if i.confidence is not None]
        return min(scored) if scored else None

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "created_at": self.created_at,
            "conclusion": self.conclusion,
            "documents": self.documents,
            "sources": sorted(self.sources),
            "weakest_confidence": self.weakest_confidence,
            "integrity_hash": self.integrity_hash,
            "items": [asdict(i) for i in self.items],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_markdown(self) -> str:
        """Render as a working-paper extract."""
        out = [f"### Evidence pack {self.pack_id}", ""]
        if self.conclusion:
            out += [f"**Conclusion.** {self.conclusion}", ""]
        out += [
            f"Prepared {self.created_at}",
            f"Documents: {', '.join(self.documents)}",
            f"Sources: {', '.join(sorted(self.sources))}",
        ]
        if self.weakest_confidence is not None:
            out.append(f"Weakest citation confidence: {self.weakest_confidence:.2f}")
        out += ["", "| Source | Document | Field | Value | Confidence |",
                "| --- | --- | --- | --- | --- |"]
        for i in self.items:
            conf = "-" if i.confidence is None else f"{i.confidence:.2f}"
            out.append(f"| {i.source_system} | {i.document_id} | `{i.field_path}` | {i.value} | {conf} |")
        if self.integrity_hash:
            out += ["", f"Integrity hash `{self.integrity_hash}`"]
        return "\n".join(out)


# ---------------------------------------------------------------------------
class EvidenceGenerator:
    """Builds an evidence pack from one or more source documents."""

    def __init__(self, *documents: dict, positions: Optional[dict] = None):
        if not documents:
            raise ValueError("At least one source document is required.")
        self._documents = list(documents)
        # (document_id, field_path) -> Position, populated when the documents
        # were read from PDF. Citations then carry the page and rectangle the
        # value was read from, which is what allows the evidence to be cropped
        # from the original page rather than merely asserted.
        self._positions = positions or {}
        self._items: list[EvidenceItem] = []

    @classmethod
    def from_pdf(cls, *paths) -> "EvidenceGenerator":
        """Build from PDF documents rather than structured records.

        Every citation made against a generator built this way carries the page
        and rectangle where the value was found.
        """
        from pdf_source import read_document

        documents = []
        positions: dict[tuple[str, str], Any] = {}
        for path in paths:
            document, found = read_document(path)
            documents.append(document)
            for field_path, position in found.items():
                positions[(document["document_id"], field_path)] = position
        return cls(*documents, positions=positions)

    # -- field resolution -------------------------------------------------
    @staticmethod
    def _resolve(document: dict, path: str) -> Any:
        current: Any = document
        for part in path.split("."):
            match = _INDEX.match(part)
            if match is None:
                raise FieldNotFound(f"Malformed field path segment: {part!r}")
            name, index = match.group("name"), match.group("index")

            if not isinstance(current, dict) or name not in current:
                raise FieldNotFound(path)
            current = current[name]

            if index is not None:
                if not isinstance(current, list) or int(index) >= len(current):
                    raise FieldNotFound(path)
                current = current[int(index)]
        return current

    def _document_for(self, document_id: Optional[str]) -> dict:
        if document_id is None:
            return self._documents[0]
        for doc in self._documents:
            if doc.get("document_id") == document_id:
                return doc
        raise FieldNotFound(f"No document loaded with id {document_id!r}")

    # -- citation ---------------------------------------------------------
    def cite(
        self,
        field_path: str,
        *,
        document_id: Optional[str] = None,
        confidence: Optional[float] = None,
        page: Optional[int] = None,
        bounding_box: Optional[tuple[float, float, float, float]] = None,
        note: Optional[str] = None,
    ) -> EvidenceItem:
        """Record one value as evidence. Raises if the field is absent."""
        document = self._document_for(document_id)
        value = self._resolve(document, field_path)

        # Fill the page and rectangle from the parse where the caller did not
        # supply them and the document was read from a PDF.
        located = self._positions.get((document.get("document_id"), field_path))
        if located is not None:
            page = located.page if page is None else page
            bounding_box = located.rect if bounding_box is None else bounding_box

        item = EvidenceItem(
            source_system=document.get("source_system", "unknown"),
            document_id=document.get("document_id", "unknown"),
            document_type=document.get("document_type", "unknown"),
            field_path=field_path,
            value=value,
            confidence=confidence,
            page=page,
            bounding_box=bounding_box,
            note=note,
        )
        self._items.append(item)
        return item

    def cite_many(self, *field_paths: str, **kwargs) -> list[EvidenceItem]:
        return [self.cite(p, **kwargs) for p in field_paths]

    def try_cite(self, field_path: str, **kwargs) -> Optional[EvidenceItem]:
        """Cite a field that may legitimately be absent.

        Records the absence explicitly rather than omitting it, so a reviewer
        can distinguish "not present on the document" from "not checked".
        """
        try:
            return self.cite(field_path, **kwargs)
        except FieldNotFound:
            document = self._document_for(kwargs.get("document_id"))
            item = EvidenceItem(
                source_system=document.get("source_system", "unknown"),
                document_id=document.get("document_id", "unknown"),
                document_type=document.get("document_type", "unknown"),
                field_path=field_path,
                value=None,
                confidence=None,
                note="field absent from source document",
            )
            self._items.append(item)
            return None

    # -- output -----------------------------------------------------------
    def pack(self, conclusion: Optional[str] = None) -> EvidencePack:
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = json.dumps([asdict(i) for i in self._items], sort_keys=True, default=str)
        digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
        return EvidencePack(
            pack_id=f"EP-{uuid.uuid4().hex[:10]}",
            created_at=created,
            conclusion=conclusion,
            items=list(self._items),
            integrity_hash=digest,
        )

    def reset(self) -> None:
        self._items.clear()

