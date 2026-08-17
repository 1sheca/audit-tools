"""Agent-facing tools.

The three tools in this repository are plain Python libraries. This module is
what makes them callable by an agent in Microsoft Agent Framework.

Nothing here contains audit logic. Every function is a thin translation layer
with four jobs:

  1. Describe the tool so the model knows when to call it. The docstring and the
     parameter descriptions are read by the model at decision time. They are not
     documentation — they are the control surface. A vague description produces
     a tool called at the wrong moment.

  2. Accept only simple typed arguments. The model can supply a string, a number
     or a boolean. It cannot supply a Python object, so file paths and document
     ids are the currency here.

  3. Return plain data the model can read. Dictionaries and lists of primitives.
     No custom classes, no Decimal, no dataclass instances.

  4. Never raise into the agent. An uncaught exception ends the agent run. Every
     failure comes back as ``{"ok": False, "error": ...}`` so the model can read
     what went wrong and decide what to do about it.

Registration with MAF is inline — the functions are passed directly, and the
schema is generated from the type hints:

    from agent_framework.foundry import FoundryChatClient
    from agent_tools import THREE_WAY_MATCH_TOOLS

    agent = FoundryChatClient(...).as_agent(
        instructions="...",
        tools=THREE_WAY_MATCH_TOOLS,
    )

The module imports without agent_framework installed, so it can be tested
locally before any Azure access exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Optional

from evidence_generator import EvidenceGenerator, FieldNotFound
from pdf_source import NoTextLayer, UnknownDocumentType, read_document
from search_and_snip import Document
from sum_finding import SumFinder

__all__ = [
    "read_document_fields",
    "check_document_arithmetic",
    "find_value_in_document",
    "snip_value_from_document",
    "build_evidence_pack",
    "DOCUMENT_TOOLS",
    "ARITHMETIC_TOOLS",
    "EVIDENCE_TOOLS",
    "THREE_WAY_MATCH_TOOLS",
    "ALL_TOOLS",
    "set_document_root",
]

# Where PDFs are resolved from. The agent supplies a document id, never a path,
# so it cannot be steered into reading an arbitrary file on the host.
_ROOT = Path(__file__).resolve().parent.parent / "data" / "pdf"


def set_document_root(path: str | Path) -> None:
    """Point the tools at a document store. Call once at start-up."""
    global _ROOT
    _ROOT = Path(path)


def _fail(message: str, **extra: Any) -> dict:
    return {"ok": False, "error": message, **extra}


def _resolve(document_id: str) -> Path:
    """Turn a document id into a path inside the document root, or raise.

    The id is reduced to its final path component first. A model that has read a
    malicious document could otherwise be talked into requesting '../../secrets'.
    """
    name = Path(document_id).name
    if not name or name.startswith("."):
        raise ValueError(f"{document_id!r} is not a usable document id")
    path = (_ROOT / name).with_suffix(".pdf")
    if not path.exists():
        raise FileNotFoundError(f"No document {name} in the document store")
    return path


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def read_document_fields(
    document_id: Annotated[
        str,
        "The document identifier, for example 'INV-2026-1005', 'PO-0089146' or "
        "'CTR-3302'. Not a file path.",
    ],
) -> dict:
    """Read the fields printed on an invoice, purchase order or contract.

    Returns exactly what the document states, including its line items and
    totals. Values are NOT corrected: if a document states a subtotal that
    disagrees with its own line items, the stated figure is returned. Use
    check_document_arithmetic to find out whether the figures are consistent.

    Call this first when you need to know what a document says. A field that is
    absent from the document is absent from the result rather than empty or
    zero — absence is a finding, not a blank.

    Only works on documents with a text layer. A scanned image returns an error
    saying so.
    """
    try:
        path = _resolve(document_id)
        document, positions = read_document(path)
    except (FileNotFoundError, ValueError) as exc:
        return _fail(str(exc))
    except NoTextLayer:
        return _fail(
            f"{document_id} is a scan with no text layer and cannot be read by "
            f"deterministic parsing. It requires a document extraction service.",
            requires_extraction_service=True,
        )
    except UnknownDocumentType:
        return _fail(f"{document_id} does not match any known document layout.")

    return {
        "ok": True,
        "document": document,
        "locatable_fields": sorted(positions),
    }


# ---------------------------------------------------------------------------
# arithmetic
# ---------------------------------------------------------------------------
def check_document_arithmetic(
    document_id: Annotated[
        str, "The document identifier, for example 'INV-2026-1004'. Not a file path."
    ],
    reporting_tolerance: Annotated[
        float,
        "Differences at or below this amount are treated as rounding and not "
        "reported as findings. Defaults to 1.00 in document currency. Only "
        "change this if the audit scope specifies a different threshold.",
    ] = 1.00,
) -> dict:
    """Recompute every figure printed on a document and report what disagrees.

    Checks line extensions, line tax, line totals, the subtotal, the tax total
    and the grand total. The grand total is checked against the document's own
    stated subtotal and tax, so a wrong grand total cannot be hidden by an
    equally wrong subtotal.

    Use this to answer 'do the numbers on this document add up'. It is
    arithmetic only — it says nothing about whether the document agrees with any
    other document. It is deterministic and exact, so trust its result over your
    own calculation.

    Distinguishes rounding differences from material ones. Only material
    discrepancies are findings.
    """
    try:
        path = _resolve(document_id)
        report = SumFinder.from_pdf(path, reporting_tolerance=reporting_tolerance).check()
    except (FileNotFoundError, ValueError) as exc:
        return _fail(str(exc))
    except NoTextLayer:
        return _fail(f"{document_id} is a scan and cannot be read.",
                     requires_extraction_service=True)

    return {
        "ok": True,
        "document_id": report.document_id,
        "checks_run": report.checks_run,
        "arithmetic_agrees": report.balanced,
        "material_discrepancies": [
            {
                "check": d.check,
                "field": d.location,
                "stated": float(d.stated),
                "computed": float(d.expected),
                "difference": float(d.stated - d.expected),
            }
            for d in report.material
        ],
        "rounding_only": [
            {"check": d.check, "difference": float(d.stated - d.expected)}
            for d in report.discrepancies
            if d.severity != "material"
        ],
    }


# ---------------------------------------------------------------------------
# locating and cropping
# ---------------------------------------------------------------------------
def find_value_in_document(
    document_id: Annotated[str, "The document identifier. Not a file path."],
    search_text: Annotated[
        str,
        "The exact text to find on the page, for example '1,400.00' or "
        "'Fibre trunk cable 500m'. Match the formatting as printed, including "
        "thousands separators.",
    ],
) -> dict:
    """Find where a piece of text appears on a document's pages.

    Returns the page number and rectangle of every occurrence. Use this when you
    need to prove a value is present on a document, or before cropping it to an
    image with snip_value_from_document.

    Returns an empty list of hits when the text is not on the page. That is a
    valid answer, not an error — it means the document does not say what was
    expected.
    """
    try:
        path = _resolve(document_id)
        with Document(path) as doc:
            hits = doc.search(search_text)
    except (FileNotFoundError, ValueError) as exc:
        return _fail(str(exc))
    except NoTextLayer:
        return _fail(f"{document_id} is a scan and cannot be searched.",
                     requires_extraction_service=True)

    return {
        "ok": True,
        "document_id": document_id,
        "search_text": search_text,
        "found": bool(hits),
        "hits": [
            {"page": h.page, "rectangle": [round(v, 1) for v in (h.x0, h.y0, h.x1, h.y1)]}
            for h in hits
        ],
    }


def snip_value_from_document(
    document_id: Annotated[str, "The document identifier. Not a file path."],
    search_text: Annotated[
        str, "The text to locate and crop, formatted as it is printed on the page."
    ],
    whole_row: Annotated[
        bool,
        "True crops the full table row containing the text, which usually reads "
        "better as audit evidence because it keeps the surrounding context. "
        "False crops only the text itself.",
    ] = True,
) -> dict:
    """Crop the part of a document page containing a value, as an image.

    Produces a PNG with the located value outlined, suitable for attaching to a
    working paper. Use this when a finding needs to be shown rather than only
    stated.

    Crop the value on each document that a comparison rests on — for example the
    invoiced rate on the invoice and the ceiling rate on the contract — so a
    reviewer can see both without opening either file.
    """
    try:
        path = _resolve(document_id)
        out_dir = Path("out") / "agent_snips"
        out_dir.mkdir(parents=True, exist_ok=True)
        with Document(path) as doc:
            hits = doc.search(search_text)
            if not hits:
                return _fail(
                    f"{search_text!r} does not appear on {document_id}. Nothing "
                    f"was cropped.",
                    found=False,
                )
            safe = "".join(c if c.isalnum() else "_" for c in search_text)[:30]
            target = out_dir / f"{document_id}-{safe}.png"
            hit = hits[0]
            if whole_row:
                doc.snip_row(hit, target, highlight=True)
            else:
                doc.snip(hit, target, highlight=True)
    except (FileNotFoundError, ValueError) as exc:
        return _fail(str(exc))
    except NoTextLayer:
        return _fail(f"{document_id} is a scan and cannot be cropped.",
                     requires_extraction_service=True)

    return {
        "ok": True,
        "document_id": document_id,
        "image_path": str(target),
        "page": hit.page,
        "occurrences_found": len(hits),
    }


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------
def build_evidence_pack(
    conclusion: Annotated[
        str,
        "The finding this evidence supports, stated in one or two sentences. "
        "Write what was found and why it matters, for example 'Invoiced unit "
        "price of 1,400.00 exceeds the contracted maximum of 1,250.00'.",
    ],
    citations: Annotated[
        list[dict],
        "The fields the conclusion rests on. Each entry is an object with "
        "'document_id' and 'field_path', for example "
        "{'document_id': 'INV-2026-1005', 'field_path': 'lines[0].unit_price'}. "
        "Field paths come from the 'locatable_fields' list returned by "
        "read_document_fields. Cite every value the conclusion depends on and "
        "nothing else.",
    ],
) -> dict:
    """Assemble the citations behind a finding into a reviewable evidence pack.

    Each citation records the value, the document it came from, the source
    system, and the page and rectangle where it appears — so a reviewer can
    check every figure against the original document.

    Call this once, after the finding is established, not while investigating.
    A field that cannot be found is recorded as absent rather than dropped,
    because a missing field is frequently the point of the finding.

    The pack reports the weakest citation's confidence, not the average: a pack
    is only as reliable as its least reliable citation. It also carries an
    integrity hash so later alteration is detectable.
    """
    if not citations:
        return _fail("An evidence pack needs at least one citation.")

    ids: list[str] = []
    for entry in citations:
        doc_id = entry.get("document_id")
        if not doc_id:
            return _fail("Every citation needs a 'document_id'.")
        if doc_id not in ids:
            ids.append(doc_id)

    try:
        paths = [_resolve(i) for i in ids]
        generator = EvidenceGenerator.from_pdf(*paths)
    except (FileNotFoundError, ValueError) as exc:
        return _fail(str(exc))
    except NoTextLayer:
        return _fail("One of the documents is a scan and cannot be cited.",
                     requires_extraction_service=True)

    missing: list[str] = []
    for entry in citations:
        field_path = entry.get("field_path")
        if not field_path:
            return _fail("Every citation needs a 'field_path'.")
        item = generator.try_cite(field_path, document_id=entry["document_id"])
        if item is None or item.value is None:
            missing.append(f"{entry['document_id']}:{field_path}")

    pack = generator.pack(conclusion=conclusion)
    return {
        "ok": True,
        "pack_id": pack.pack_id,
        "conclusion": pack.conclusion,
        "documents": list(pack.documents),
        "source_systems": sorted(pack.sources),
        "weakest_confidence": pack.weakest_confidence,
        "integrity_hash": pack.integrity_hash,
        "fields_not_found": missing,
        "citations": [
            {
                "document_id": i.document_id,
                "field_path": i.field_path,
                "value": i.value,
                "source_system": i.source_system,
                "page": i.page,
                "located_on_page": i.bounding_box is not None,
            }
            for i in pack.items
        ],
        "markdown": pack.to_markdown(),
    }


# ---------------------------------------------------------------------------
# tool sets
# ---------------------------------------------------------------------------
# Give an agent the smallest set that does its job. Every extra tool is another
# choice the model can get wrong, and a longer prompt on every single turn.
DOCUMENT_TOOLS = [read_document_fields, find_value_in_document]
ARITHMETIC_TOOLS = [check_document_arithmetic]
EVIDENCE_TOOLS = [build_evidence_pack, snip_value_from_document]

THREE_WAY_MATCH_TOOLS = [
    read_document_fields,
    check_document_arithmetic,
    build_evidence_pack,
    snip_value_from_document,
]

ALL_TOOLS = [
    read_document_fields,
    check_document_arithmetic,
    find_value_in_document,
    snip_value_from_document,
    build_evidence_pack,
]
