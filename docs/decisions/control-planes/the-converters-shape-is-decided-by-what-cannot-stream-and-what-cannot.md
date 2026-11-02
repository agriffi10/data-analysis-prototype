---
type: Decision
title: "The converter's shape is decided by what cannot stream and what cannot be retried (SPEC-222)"
description: "**A conversion reads from the ACTOR'S space and writes to the DESTINATION'S**, and the two coincide only for a personal destination — which is why a suite whose fixtures are all personal cannot tell them apart, and why one shipped reading the result object out of the shared bucket. Its **types come from the metadata**, where a decimal's parameters are **never in `Type`** — captured — and are read from `Precision`/`Scale`, which no capture route available here can show are populated; the verb refuses the column rather than guessing a scale, so being wrong about that costs a loud refusal and not a silently rounded number. The vocabulary is closed and **refuses rather than falling back**. Excel is the one format that cannot stream, and its memory is spent per **CELL** — a one-byte NULL costs ~250 bytes — so it is capped by a cell count taken from the CSV **before** anything is built, while the others are set by the disk. A byte cap alone cannot be both safe and useful, and one admitted a result that ran the converter out of memory. `Convert` retries **`TransientError` only**: a `Lambda.*` retry can re-run an invocation that already completed its conditional `PutObject`, and it then meets its own object and reports `destination_occupied` for a save that succeeded."
---

**The size cap is per format because Excel cannot stream.** Parquet and JSON are `scan_csv` into
`sink_*`, so memory holds a batch and the ceiling is the scratch disk. Excel has no streaming
writer: polars materialises the frame and xlsxwriter builds the whole workbook beside it, at a
peak ~~measured on the fleet image at 23–32x the input CSV~~ — **superseded by SPEC-230**: the peak
is set per CELL, not per byte, and that figure was one shape's; see *Excel is bounded by cells*
below. One cap for all three is dishonest in
whichever direction it is set — at Excel's bound it refuses Parquet conversions that work
comfortably, and at the disk bound it promises an Excel conversion that runs out of memory two
thirds of the way through. The caps are recomputed from the measured constants by a test, so a
hand edit to either side is red, and the constants are held equal to the module's `locals.tf`
because the whole derivation is against numbers Terraform has to actually deploy.

**`Convert` retries `TransientError` alone, once.** Every other Task on this plane also retries
the four `Lambda.*` service errors three times, and here that would be a correctness bug rather
than a cost: those errors cover a response lost *after* the function completed, so a retry
re-invokes a converter that already completed its `If-None-Match` `PutObject`, meets its own
object, and reports `destination_occupied` — manufacturing the one refusal the conditional-write
design exists to make truthful. The verb raises `TransientError` only before the upload begins,
and a test reads that from the AST rather than the source text, because the docstring explaining
the rule names the word the sweep looks for.

**A refusal that cannot fire is worse than no refusal.** FR-004 asked for a refusal above Excel's
16,384 columns. It could never run: the described columns travel on a Step Functions state capped
at 256 KB, which a realistic column entry fills somewhere between ~2,500 and ~6,400 columns —
measured across entry widths, and the FLOOR is what a cap is set against. So the ceiling that
exists is the transport's, it is refused in describe-results before the columns are put on the
state that cannot carry them, and it applies to every format. The dead code was removed rather
than kept as a fence that stops nobody.

**Two things polars does silently, both found by measuring rather than reading.** `scan_csv` with
`schema_overrides` whose keys do not match the header misreads the file with no error: polars 1.12
RENAMED the columns to the override keys and applied the types POSITIONALLY, and 1.44.2 ignores
the unmatched keys and reads those columns as text; given a reordered header it keeps the file's
order and matches types by name. Either way a divergence between what Athena reported and what
Athena wrote yields a file with the wrong labels or the wrong types and no complaint, so the header
is checked against the metadata before the typed read. And `sink_ndjson` writes a timestamp as
`2020-01-02 03:04:05.123` — a space separator with trailing zeros stripped, neither ISO-8601 nor
to microseconds — so datetime columns are cast explicitly before the sink.

**The result object is read from the ACTOR's bucket and written to the DESTINATION's.** They are
the same string for a personal destination and different for a shared one, so a suite whose
fixtures are all personal agrees with a converter that has them the wrong way round — which is
what shipped, and what two review frames caught independently. The fake in that verb's tests now
answers the way the IAM grant does, refusing a read aimed anywhere but the user-space bucket.

**A conversion's types come from the metadata**, where a decimal's parameters are never in `Type` and are read from `Precision`/`Scale`, which no capture route available here can show are populated; the verb refuses the column rather than guessing a scale, so being wrong about that costs a loud refusal and not a silently rounded number. The vocabulary is closed and refuses rather than falling back.

## History

### 2026-09-06

- **Settled:** SPEC-222.
