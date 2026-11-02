---
type: Decision
title: "The polars 1.44 pin, and what the move owed the code written around 1.12 (SPEC-245)"
description: "**polars reads only bytes this code fetched, and a polars panic is not an `Exception`.** Over a Python file object on S3, 1.44 reads the whole object, so the Parquet probe hands it the footer alone (`bounded_read.read_parquet_footer`); and a Rust panic surfaces as pyo3's `PanicException`, a `BaseException` that walks past `except Exception`, so both schema probes catch it beside `Exception`. The converter's sinks do not: what they read is Athena's own CSV, not a user's file."
---

The fleet runs **`polars==1.44.2`**, pinned exactly in the two requirements files that declare it
and read fleet-wide because the image installs every requirements file into one site-packages. The
move was made for one defect — 1.12's streaming CSV reader mis-split a large result holding
multi-line values, refusing a whole save and writing a column-subset save WRONG — and what this
entry records is the four things the move owed beyond the pin, because each was invisible to a
suite that stayed green on the new version.

**polars is handed only bytes this code fetched itself.** The Parquet schema probe used to hand
polars a Python file object over S3 ranged GETs and trust it to seek to the footer. 1.44 implements
`read_parquet_schema` as `scan_parquet(...).collect_schema()`, which reads such an object whole, so
the probe that was bounded on 1.12 would have pulled a large source into a 1,024 MB function with
every schema still right. `cpcommon.bounded_read.read_parquet_footer` now fetches the trailer and
then exactly the footer, and hands polars an in-memory file of the footer alone — bounded however
polars reads it. The trailer checks live once, in `cpcommon.parquet_trailer`, shared with the
converter's footer decoder; a zero-length footer is refused there because its range would be
inverted and S3 answers an inverted range with the whole object; and every response's declared
length is checked before its body is read. This shipped first, on 1.12, so the version move changed
nothing about how a probe reads.

**A polars panic is not an `Exception`.** 1.44 panics on some damaged Parquet footers where 1.12
raised `ComputeError`, and a pyo3 `PanicException` derives from `BaseException`, so it escaped both
schema probes' `except Exception` as a fault with no named refusal. Both now catch it beside
`Exception`; a fuzzed footer is the fixture, and it discriminates only on 1.44.

**A stopgap for a library defect is retired with the defect, and the keyword it used was already
gone.** The projection-pushdown switch that turned 1.12's wrong column-subset file into a refusal
was a keyword 1.44's sinks reject with a `TypeError`, which the writers would have turned into a
refusal of every streamed save. It was retired rather than translated, and the guard that remains
converts the mis-splitting shape in every streamed format, whole and projected, row for row — red on
1.12.

**Measured caps are re-measured on the new library, and the new runs JOIN the evidence.** 1.44's
fixed memory cost is larger, so the Excel baseline rose and the cell cap fell from 4,100,000 to
3,900,000; no cap rose, because every corpus row keeps its highest peak over both versions' runs
and every constant the larger of its old value and what the joined corpus derives (for the covered
width, the smaller). A run slowed by
a concurrent job keeps its memory and loses its rates: CPU contention lowers a rate but cannot
inflate a cgroup peak. The per-run figures are in `rccommon.config.MEASURED_ON` and #865; the
reasoning and the live checks: `spec-delivery/SPEC-245`.

## History

### 2026-09-21

- **Settled:** SPEC-245.
