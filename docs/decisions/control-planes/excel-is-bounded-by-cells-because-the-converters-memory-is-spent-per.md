---
type: Decision
title: "Excel is bounded by cells, because the converter's memory is spent per cell (SPEC-230)"
description: "**Excel is capped by a cell count, because the converter's memory is spent per cell**: a byte cap admitted a result the converter could not hold. **A refusal that cannot fire is a fence that misleads everyone downstream.** Excel's 16,384-column ceiling is unreachable here — the described columns ride the 256 KB state, which a realistic column entry fills between ~2,500 and ~6,400 — so the cap that exists is the TRANSPORT's, sits in describe-results, and applies to every format. Reasoning: `the-converters-shape-is-decided-by-what-cannot-stream-and-what-cannot.md`."
---

**The byte cap admitted a result the converter could not hold, and every up-front check agreed.**
A 1,048,575 × 15 one-character result — 62,914,590 bytes, under the 64 MB cap and exactly at
Excel's row ceiling — ran the converter for its full ten minutes at its full 3,008 MB, and the user
was told "something went wrong". The cap had been derived per CSV BYTE from one wide shape, and the
offline time check that stood behind it measured a wide shape too, so it passed. The Excel path's
peak is set by CELLS: polars hands xlsxwriter a Python copy of every cell and xlsxwriter stores each
again, at no less than about 240 bytes a cell whatever it holds — more for long text or a narrow
result — while a CSV cell can be one byte. A byte cap
safe for the worst shape would be about 8 MB.

**Cells, not bytes, and not a streaming writer — the owner's call.** xlsxwriter refuses
`add_table()` in `constant_memory` mode, and polars' `write_excel` always builds a table from
`df.rows()`, so streaming means a hand-written writer that loses the Excel table — and still needs
a cell cap, because time is per cell as well. It is the follow-up if the cap proves too small.

**The rows are counted in the converter, not in describe-results.** The only cheap source up front
is Athena's runtime statistics, which the API reference says may not be returned and are omitted
under Lake Formation row filters, and the only fallback for a missing count is the byte cap this
replaced. The converter counts through ONE column with the real CSV reader, and both Excel
refusals are decided from that before the frame exists, the row ceiling first — and asked again of
the frame's height once it is built. **Not `pl.len()`**: polars' fast count projects nothing, and
under polars 1.12 it tracked quotes chunk by chunk, so across threads it miscounted a quoted
newline, and a review showed it admitting a result over Excel's ceiling whose rows xlsxwriter then
dropped, reported as saved. 1.44.2 counts that shape exactly; the count through a column was right
on both and stays.
Each refusal names its code where it is raised, because the plane's vocabulary sweep reads a
literal first argument.

**The cap is derived from a measured model held to a corpus, and four things were learned
measuring it.** Units: Lambda's MB is MiB, and one anchor subtracted a decimal figure from a binary
one, which only a review caught. The anchor: the production run it rests on was rebuilt from
Athena's own history, to the byte, rather than approximated by a shape that looked similar. The
cgroup slope moves by several percent run to run, so every constant is rounded up above the worst
run and the 15% reserve stays. And one anchor does not transfer: the live conversion at the cap
came in well above both the band predicted from the anchor and the corpus guard's own figure, and
inside the model, so a re-derivation is validated by a live conversion as the plane page's Traps
say, not by the anchor or by a green guard. The guard scales every measured shape to
the largest input the caps admit, through the production predicate; under the byte cap alone the
production shape fails it.

**An Excel conversion that runs out of time or memory is named**, because neither can raise and
the notifier otherwise words the Lambda's error as the fallback. The streamed formats keep the
fallback — pointing a Parquet request at Parquet would be wrong.

## History

### 2026-09-10

- **Settled:** SPEC-230.
