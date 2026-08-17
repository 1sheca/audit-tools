# Audit tools

Three standalone tools from the shared tool layer of the internal audit
automation architecture. Each is independent: separate package, separate demo,
separate tests. None imports another.

All three read **real PDF documents** in `data/pdf/`. There is no other data
source. Every figure they check, cite or crop is read off a page.

| Tool | What it does | Needs a model? |
| --- | --- | --- |
| `evidence_generator` | Records where every cited value came from, with page coordinates | No |
| `sum_finding` | Recomputes and verifies the arithmetic printed on the page | No |
| `search_and_snip` | Locates text in a PDF and crops it to an image | No |

A fourth package, `pdf_source`, is the reader the first two share. It parses a
PDF into structured values and returns the position of every value it found.
The three tools remain independent of one another; two of them depend on this
reader in the same way they depend on pymupdf.

All three are deterministic. No cloud service, no API key, no model call.

## Setup

    pip install -r requirements.txt

## Running each tool

    python -m evidence_generator.demo             cite from the PDFs
    python -m evidence_generator.demo --snip     crop each citation from its page
    python -m evidence_generator.demo --markdown
    python -m evidence_generator.demo --json
    python -m evidence_generator.demo --records  read the JSON instead

    python -m sum_finding.demo                   check the figures on the page
    python -m sum_finding.demo --verbose
    python -m sum_finding.demo --document INV-2026-1004
    python -m sum_finding.demo --json            read the JSON instead

    python -m search_and_snip.demo
    python -m search_and_snip.demo --scan

    python -m pytest -q

The 20 documents in `data/pdf/` are part of the repository — 9 invoices, 6
purchase orders, 5 contracts. There is no build step and no other data source.
Every figure the tools check, cite or crop is read off one of those pages.

## The dataset

Twenty documents: 9 invoices, 6 purchase orders, 5 contracts. Field sets follow
the conventions the real documents use rather than a convenient internal shape.

Invoices carry seller and buyer blocks, tax registration numbers, issue and due
dates, payment terms, per-line unit of measure, tax rate and tax amount,
subtotal, tax total and gross total, currency and remittance details. Purchase
orders carry a requisition number, buyer contact, delivery date, ship-to and
bill-to, contract reference, item numbers and net values. Contracts carry
parties, effective and expiry dates, governing law, a payment clause, a rate
schedule with maximum unit rates, and a renewal clause.

The population is deliberately imperfect, in the ways real populations are:

- `INV-2026-1002` quotes its purchase order as `po 89143`, not `PO-0089143`
- `INV-2026-1004` states a subtotal that does not agree with its own lines
- `INV-2026-1006` has tax drift of seven cents across six lines
- `INV-2026-1007` quotes no purchase order at all
- `INV-2026-1008` has a transposed grand total, and names a purchase order that does not exist
- `INV-2026-1009` omits payment terms entirely

## agent_tools

The wrapper that makes the three tools callable by an agent in Microsoft Agent
Framework. It contains no audit logic — it translates.

Each function takes only simple typed arguments (a document id, a search string,
a number), returns plain JSON-serialisable data, and never raises: a failure
comes back as `{"ok": false, "error": ...}` so the agent can read what went
wrong instead of the run ending.

The docstrings and the `Annotated` parameter descriptions are not documentation.
They are the text the model reads when deciding whether to call a tool and what
to pass it. They are the control surface, and they are why this layer belongs
with the tools rather than with the agent.

Registration is inline; the schema is generated from the type hints:

    from agent_framework.foundry import FoundryChatClient
    from agent_tools import THREE_WAY_MATCH_TOOLS

    agent = FoundryChatClient(...).as_agent(
        instructions="...",
        tools=THREE_WAY_MATCH_TOOLS,
    )

Document ids are resolved inside a fixed document root, so a model cannot be
steered into reading an arbitrary file. `set_document_root()` points it at a
different store.

The module imports without `agent-framework` installed, so it is testable before
any Azure access exists.

## pdf_source

Parses an invoice, purchase order or contract from PDF into structured values,
and records where on the page each value was found. Layout is recognised from
the page header; values are read by label anchoring and column proximity rather
than fixed coordinates.

It reads the parties too — who issued the document and who it is addressed to.
Whether the vendor named on an invoice is the vendor named on the purchase order
is itself a three-way match check, so party identity is a field, not decoration.

It does not correct what it reads. Where a document states a subtotal that
disagrees with its own lines, the stated figure is what comes back — a parser
that silently repairs a document destroys the finding it was built to surface.
Fields that are absent stay absent rather than defaulting.

Requires a text layer. A scan raises `NoTextLayer`.

## evidence_generator

Given source documents and the fields a conclusion rests on, produces an
evidence pack: a citable record of where each value came from, what it was, and
how reliably it was read. Holds no audit logic and decides nothing.

Citing a field that does not exist raises `FieldNotFound` rather than returning
nothing — silently citing a missing value is how an evidence pack ends up
asserting something the document never said. Where a field may legitimately be
absent, `try_cite` records the absence explicitly, so a reviewer can tell "not
on the document" from "not checked".

Pack confidence is the weakest citation, not the average: a pack is only as
reliable as its least reliable citation. Each pack carries an integrity hash so
a later change to the evidence is detectable.

Built with `EvidenceGenerator.from_pdf(...)`, every citation carries the page
and rectangle the value was read from. `--snip` then crops each one from its
source document, which is what turns a stated finding into a showable one: the
demo produces the invoiced rate, the ordered rate and the contracted ceiling as
three cropped images from three different documents.

## sum_finding

Recomputes every arithmetic relationship in a document and reports where it
does not agree with itself: line extension, line tax, line total, subtotal, tax
total, grand total, and purchase order value.

All arithmetic is `Decimal`. Binary floating point is not used anywhere in the
module — an audit tool that reports a variance of 0.00000000004 has failed at
the first step.

Two tolerances are distinguished and are not interchangeable. Rounding
tolerance absorbs legitimate half-cent differences arising from where a
document rounds. Reporting tolerance is a business decision about what size of
discrepancy is worth raising. Seven cents of drift across six lines is not the
same event as a transposed figure, and the tool does not report them alike.

The grand total is checked against the document's own stated subtotal and tax,
so a wrong grand total cannot be masked by an equally wrong subtotal.

`SumFinder.from_pdf(...)` checks the figures printed on the page. The tests
assert that reading a document from PDF and from its structured record reach
the same verdict, so a discrepancy is a property of the document rather than of
how it was read.

## search_and_snip

Finds text in a PDF, returns where it sits, and crops that region to an image.
This is what turns a stated figure into showable evidence: an auditor reading
"the rate exceeds the contracted maximum" has to take it on trust, while an
auditor looking at that line cropped from the original invoice does not.

Supports literal search, regular-expression search for anything with a known
shape, label-anchored lookup (read the value printed beneath or beside a label,
when the value is not known in advance), and widening a hit to its full table
row so the crop carries context rather than a bare number.

Highlighting renders from a copy, so the source PDF is never modified.

**Limitation.** Everything here requires a text layer. A scanned or
photographed document raises `NoTextLayer` and must go to a cloud extraction
service instead. This is a real boundary of the deterministic route, not a
defect.

## Documents that run over more than one page

A document is read as one continuous sequence of rows across all its pages. A
line table cut by a page foot continues at the top of the next page, and the
totals printed there are found. Every value carries the page it was printed
on, so an evidence crop is taken from that page.

Rows are never merged across a page break, and a label never takes its value
from the following page. The layout is identified from the top of any page,
not only the first.

The sample documents are all one page. `tests/test_multipage.py` republishes
four of them across two pages and requires the reader to produce exactly what
it produced from one page — same figures, same fields, no line counted twice.

## The same row twice

A row can be extracted twice for reasons that have nothing to do with what was
billed, and it can be printed twice because the document genuinely bills it
twice. These are not the same thing and are not treated the same way.

Removed:

- text printed at the same coordinates more than once, which is what a second
  text layer produces — usually a scan that has been through OCR, leaving
  invisible text beneath the visible text;
- a row on a page seam rendered onto both pages of the break.

Position is what makes this safe. Two glyphs cannot occupy the same point on
the page and mean different things.

Kept:

- a line printed a second time elsewhere in the table. That is a duplicate
  billed line, it is an audit finding, and removing it would report a clean
  invoice where there is a real exception. It reaches the caller unchanged,
  and the arithmetic then disagrees with the stated subtotal, which is the
  point.

Anything removed is recorded on the document under `removed_duplicates`, with
a count and a reason. Nothing is dropped invisibly.

## Two sample sets

`data/pdf/` — twenty documents, one page each, everything where it is
expected. A floor to work against.

`data/pdf-rich/` — thirteen documents that behave the way supplier documents
actually behave:

- two and three pages each, with line tables that run past the foot of a page
  and resume under a reprinted set of column headings;
- a logo on every page, a footer on every page, a signature, an approval
  stamp, a watermark;
- a process drawing, a site plan and an escalation chart sitting between the
  figures;
- totals that land on a later page than the header they belong to;
- one document that is only a scan, with no text in it at all.

Planted defects: `RINV-2026-2002` understates its subtotal by 4,000.00,
`RPO-0089203` states an order value that does not agree with its own lines,
`RINV-2026-2003` quotes a purchase order that does not exist, and
`RINV-2026-2005` quotes none at all.

Both sets ship with the repository. `rich_documents/` is how the second set
was built. No tool imports it, and deleting it leaves everything working.

Building this set found four reader defects that the one-page samples could
never have shown: a label read as touching its value was dropped, a page
footer under a table was read as a priced row, an amount printed hard against
its currency code was not seen as a number at all, and a figure set slightly
wide of its column was taking the neighbouring column and pushing every figure
after it one place along.
