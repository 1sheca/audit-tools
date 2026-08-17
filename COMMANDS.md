# Commands

Open the folder in VS Code, then **Terminal → New Terminal** (Ctrl + `).
The prompt must end in `audit-tools`.

## Setup — once

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt

If the activate line is blocked by a policy error, run this first, then retry:

    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

You should now see `(.venv)` at the start of the prompt. It must be there every
time. If you close the terminal, run `.venv\Scripts\activate` again.

If activation stays blocked, skip it and call the environment's Python directly:

    .venv\Scripts\python -m pip install -r requirements.txt
    .venv\Scripts\python -m pytest -q

## Check it works

    python -m pytest -q

128 tests. All should pass.

## The three tools

    python -m evidence_generator.demo --snip
    python -m sum_finding.demo --verbose
    python -m search_and_snip.demo

There are two sample sets. `data/pdf/` holds 20 one-page documents; the
demos read those. `data/pdf-rich/` holds 13 multi-page documents with tables
crossing page breaks, images, diagrams and one scan — the tests read those.

To rebuild the second set after editing it:

    python -m rich_documents.make

The demos read the 20 PDFs in `data/pdf/` — 9 invoices, 6 purchase orders,
5 contracts. Those documents are part of the repository. There is no build step
and no other data source.

`--snip` writes cropped evidence images to `out\evidence\`.

## Useful extras

    python -m sum_finding.demo --document INV-2026-1004    one document only
    python -m evidence_generator.demo --markdown           pack as markdown
    python -m evidence_generator.demo --json               pack as JSON
    python -m search_and_snip.demo --scan                  refusal on a scan

## If something fails

`ModuleNotFoundError` — `(.venv)` is missing from the prompt, or
`pip install -r requirements.txt` has not been run.

`data/pdf is missing` — the documents were not extracted, or were excluded when
the folder was copied. Re-extract the zip.

`python is not recognized` — Python is not on PATH. Ctrl+Shift+P →
"Python: Select Interpreter" → pick the `.venv` one.
