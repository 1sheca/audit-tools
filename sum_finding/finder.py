"""Sum finding.

A standalone tool. Given a document with line items and stated totals, it
recomputes every arithmetic relationship and reports where the document does
not agree with itself.

Six checks are performed:

    line extension      quantity x unit price  ==  stated net amount
    line tax            net amount x tax rate  ==  stated tax amount
    line total          net amount + tax       ==  stated line total
    subtotal            sum of line net        ==  stated subtotal
    tax total           sum of line tax        ==  stated tax total
    grand total         subtotal + tax total   ==  stated grand total

All arithmetic is performed in Decimal. Binary floating point is not used
anywhere in this module: 0.1 + 0.2 is not 0.3 in binary floating point, and an
audit tool that reports a variance of 0.00000000004 has failed at the first
step.

Two tolerances are distinguished. Rounding tolerance absorbs legitimate
half-cent differences arising from where a document rounds. Reporting tolerance
is a business decision about what size of discrepancy is worth raising. They
are not the same number and are not interchangeable.

    from sum_finding import SumFinder

    finder = SumFinder(document)
    report = finder.check()
    print(report.summary())
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Any, Optional

__all__ = ["SumFinder", "Discrepancy", "SumReport", "money"]

CENT = Decimal("0.01")
DEFAULT_ROUNDING_TOLERANCE = Decimal("0.02")
DEFAULT_REPORTING_TOLERANCE = Decimal("1.00")


def money(value: Any) -> Decimal:
    """Convert to Decimal without passing through float.

    str() is applied first deliberately. Decimal(0.1) inherits the binary
    representation error; Decimal(str(0.1)) does not.
    """
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Not a numeric value: {value!r}") from exc


def q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Discrepancy:
    check: str
    location: str
    expected: Decimal
    stated: Decimal
    severity: str

    @property
    def difference(self) -> Decimal:
        return q(self.stated - self.expected)

    @property
    def percentage(self) -> Optional[Decimal]:
        if self.expected == 0:
            return None
        return q(abs(self.stated - self.expected) / abs(self.expected) * 100)

    def describe(self) -> str:
        pct = "" if self.percentage is None else f"  ({self.percentage}%)"
        return (f"[{self.severity}] {self.check} at {self.location}: "
                f"stated {self.stated}, computed {self.expected}, "
                f"difference {self.difference}{pct}")


@dataclass
class SumReport:
    document_id: str
    document_type: str
    checks_run: int = 0
    discrepancies: list[Discrepancy] = field(default_factory=list)
    computed: dict[str, Decimal] = field(default_factory=dict)

    @property
    def balanced(self) -> bool:
        return not self.discrepancies

    @property
    def material(self) -> list[Discrepancy]:
        return [d for d in self.discrepancies if d.severity != "rounding"]

    def summary(self) -> str:
        head = f"{self.document_id}  ({self.document_type})  {self.checks_run} checks"
        if self.balanced:
            return head + "  ·  all arithmetic agrees"
        lines = [head + f"  ·  {len(self.discrepancies)} discrepancy(ies)"]
        for d in self.discrepancies:
            lines.append("    " + d.describe())
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "document_type": self.document_type,
            "checks_run": self.checks_run,
            "balanced": self.balanced,
            "computed": {k: str(v) for k, v in self.computed.items()},
            "discrepancies": [
                {
                    "check": d.check,
                    "location": d.location,
                    "expected": str(d.expected),
                    "stated": str(d.stated),
                    "difference": str(d.difference),
                    "percentage": None if d.percentage is None else str(d.percentage),
                    "severity": d.severity,
                }
                for d in self.discrepancies
            ],
        }


# ---------------------------------------------------------------------------
class SumFinder:
    """Recomputes and verifies every arithmetic relationship in a document."""

    def __init__(
        self,
        document: dict,
        rounding_tolerance: Decimal = DEFAULT_ROUNDING_TOLERANCE,
        reporting_tolerance: Decimal = DEFAULT_REPORTING_TOLERANCE,
    ):
        self.document = document
        self.rounding_tolerance = money(rounding_tolerance)
        self.reporting_tolerance = money(reporting_tolerance)
        self._report = SumReport(
            document_id=document.get("document_id", "unknown"),
            document_type=document.get("document_type", "unknown"),
        )

    @classmethod
    def from_pdf(cls, path, **kwargs) -> "SumFinder":
        """Build from a PDF rather than a structured record.

        The figures checked are the ones printed on the page, read back out of
        it. Nothing is taken from a structured source alongside.
        """
        from pdf_source import read_document

        document, _ = read_document(path)
        return cls(document, **kwargs)

    # -- classification ---------------------------------------------------
    def _severity(self, difference: Decimal) -> Optional[str]:
        """None where the difference is immaterial and should not be raised."""
        magnitude = abs(difference)
        if magnitude <= self.rounding_tolerance:
            return None
        if magnitude <= self.reporting_tolerance:
            return "rounding"
        return "material"

    def _compare(self, check: str, location: str, expected: Decimal, stated: Decimal) -> None:
        self._report.checks_run += 1
        expected, stated = q(expected), q(stated)
        severity = self._severity(stated - expected)
        if severity is not None:
            self._report.discrepancies.append(
                Discrepancy(check, location, expected, stated, severity)
            )

    # -- checks -----------------------------------------------------------
    def _check_lines(self) -> tuple[Decimal, Decimal]:
        net_total = Decimal("0")
        tax_total = Decimal("0")

        for line in self.document.get("lines", []):
            ref = f"line[{line.get('line_number', '?')}]"

            quantity = money(line["quantity"])
            unit_price = money(line["unit_price"])
            extension = q(quantity * unit_price)

            if "net_amount" in line:
                self._compare("line_extension", f"{ref}.net_amount",
                              extension, money(line["net_amount"]))
                net = money(line["net_amount"])
            else:
                net = extension
            net_total += net

            if "tax_rate" in line and "tax_amount" in line:
                rate = money(line["tax_rate"])
                self._compare("line_tax", f"{ref}.tax_amount",
                              q(net * rate / 100), money(line["tax_amount"]))
                tax = money(line["tax_amount"])
            else:
                tax = Decimal("0")
            tax_total += tax

            if "line_total" in line:
                self._compare("line_total", f"{ref}.line_total",
                              net + tax, money(line["line_total"]))

        return net_total, tax_total

    def _check_totals(self, net_total: Decimal, tax_total: Decimal) -> None:
        totals = self.document.get("totals")
        if not totals:
            # Purchase orders carry a single order value rather than a block.
            if "order_value" in self.document:
                self._compare("order_value", "order_value",
                              net_total, money(self.document["order_value"]))
            return

        if "subtotal" in totals:
            self._compare("subtotal", "totals.subtotal",
                          net_total, money(totals["subtotal"]))
        if "tax_total" in totals:
            self._compare("tax_total", "totals.tax_total",
                          tax_total, money(totals["tax_total"]))
        if "grand_total" in totals:
            # Checked against the document's own stated components where they
            # exist, so a wrong grand total is not masked by a wrong subtotal.
            stated_net = money(totals.get("subtotal", net_total))
            stated_tax = money(totals.get("tax_total", tax_total))
            self._compare("grand_total", "totals.grand_total",
                          stated_net + stated_tax, money(totals["grand_total"]))

    # -- entry point ------------------------------------------------------
    def check(self) -> SumReport:
        net_total, tax_total = self._check_lines()
        self._check_totals(net_total, tax_total)
        self._report.computed = {
            "lines_net": q(net_total),
            "lines_tax": q(tax_total),
            "lines_gross": q(net_total + tax_total),
        }
        return self._report

