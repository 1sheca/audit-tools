"""The agent-facing layer must never raise into an agent run.

An uncaught exception ends the run. Every failure has to come back as data the
model can read and act on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import agent_tools as t

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "pdf"

if len(list(PDF.glob("*.pdf"))) < 20:
    raise RuntimeError(
        "data/pdf is missing documents. The 20 sample PDFs are part of this "
        "repository — restore them from source control."
    )






def test_every_tool_returns_a_dict_with_an_ok_flag():
    calls = [
        t.read_document_fields("INV-2026-1005"),
        t.check_document_arithmetic("INV-2026-1004"),
        t.find_value_in_document("INV-2026-1005", "1,400.00"),
        t.snip_value_from_document("INV-2026-1005", "1,400.00"),
    ]
    for result in calls:
        assert isinstance(result, dict)
        assert result["ok"] is True


def test_unknown_document_returns_an_error_rather_than_raising():
    for call in (
        lambda: t.read_document_fields("DOES-NOT-EXIST"),
        lambda: t.check_document_arithmetic("DOES-NOT-EXIST"),
        lambda: t.find_value_in_document("DOES-NOT-EXIST", "x"),
    ):
        result = call()
        assert result["ok"] is False
        assert isinstance(result["error"], str)


def test_path_traversal_is_refused():
    """A model that has read a hostile document must not reach the filesystem."""
    result = t.read_document_fields("../../etc/passwd")
    assert result["ok"] is False


def test_results_are_json_serialisable():
    """Decimal and dataclasses cannot cross the boundary to the model."""
    import json

    json.dumps(t.check_document_arithmetic("INV-2026-1004"))
    json.dumps(t.read_document_fields("INV-2026-1005"))
    json.dumps(t.build_evidence_pack(
        "test", [{"document_id": "INV-2026-1005", "field_path": "lines[0].unit_price"}]
    ))


def test_arithmetic_tool_reports_the_planted_error():
    result = t.check_document_arithmetic("INV-2026-1004")
    assert result["arithmetic_agrees"] is False
    assert any(d["check"] == "subtotal" for d in result["material_discrepancies"])


def test_text_that_is_absent_is_reported_as_absent_not_as_failure():
    result = t.find_value_in_document("INV-2026-1005", "9,999.00")
    assert result["ok"] is True
    assert result["found"] is False


def test_evidence_pack_records_a_field_it_could_not_find():
    result = t.build_evidence_pack(
        "Rate breach.",
        [
            {"document_id": "INV-2026-1005", "field_path": "lines[0].unit_price"},
            {"document_id": "INV-2026-1005", "field_path": "delivery_note_reference"},
        ],
    )
    assert result["ok"] is True
    assert "INV-2026-1005:delivery_note_reference" in result["fields_not_found"]


def test_evidence_pack_rejects_malformed_citations():
    assert t.build_evidence_pack("x", [])["ok"] is False
    assert t.build_evidence_pack("x", [{"field_path": "a"}])["ok"] is False
    assert t.build_evidence_pack("x", [{"document_id": "INV-2026-1005"}])["ok"] is False


def test_every_registered_tool_has_a_docstring_and_annotated_parameters():
    """The docstring and parameter descriptions are what the model reads."""
    import typing

    for tool in t.ALL_TOOLS:
        assert tool.__doc__ and len(tool.__doc__) > 100, tool.__name__
        hints = typing.get_type_hints(tool, include_extras=True)
        for name, hint in hints.items():
            if name == "return":
                continue
            assert typing.get_origin(hint) is typing.Annotated, f"{tool.__name__}.{name}"
