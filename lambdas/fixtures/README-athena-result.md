# The captured Athena result set

`athena_result_all_types.csv` and `athena_result_all_types_columns.json` are one real Athena
execution, captured on 2026-09-06 from the `dat-prod-portal-wg` workgroup through the portal —
not written by hand. SPEC-222 FR-001 requires that: the file's whole purpose is to prove how
**Athena** encodes a result set, and a hand-written CSV would only prove how the author believes
it does.

## What it settles

**NULL and the empty string are different bytes.** In the data row:

```
… ,"hi","ab","",,,"[1, 2]", …
        └ char  └ CAST('' AS varchar)
                   └ CAST(NULL AS varchar)
                    └ CAST(NULL AS bigint)
```

A value present but empty is `""`. A NULL is a bare empty field with no quotes at all — for a
text column and a numeric one alike. That is exactly what polars' `scan_csv` distinguishes by
default, which is why the converter builds no helper to enforce it: the rule is the reader's
already, and this file is what proves the two agree rather than a comment asserting it.

**A decimal's parameters are not in its type.** `c_decimal` was cast `decimal(10,2)` and Athena
reports the type as bare `decimal`. That is the whole reason `describe-results` carries
`precision` and `scale` beside the name, and `rccommon.types` composes the canonical string.

**Several names differ from what the SQL asked for.** `integer` is reported `int`, `real` is
`float`, `varchar` is `string`, `char(2)` is `char`, `varbinary` is `binary`, and `ARRAY[1,2]`
is `array` with no element type. The type table maps every one of these, and the corpus in
`test_types_rccommon.py` is deliberately wider still — it also carries the parameterised spellings
this capture does not exhibit, because a narrower corpus would be a claim that Athena never
sends them.

**Three types the spec's original vocabulary did not list appear here**: `uuid`,
`interval day to second` and `interval year to month`. They were added from Athena's documented
type list before this capture existed; without them, this very query — an ordinary `SELECT` of
casts — would have refused with `unsupported_column_type`.

**Text-kept types arrive as rendered text**, which is what makes writing them as text honest
rather than lossy: `"[1, 2]"`, `"{""a"":1}"` (RFC4180 doubled quotes), `"78"` for a varbinary in
hex, `"2 00:00:00.000"` and `"0-3"` for the two intervals.

## What it does NOT settle, and why

**`Precision` and `Scale` are absent from the JSON**, and their absence is a property of the
capture route rather than of Athena. The portal's own results endpoint maps `ColumnInfo` to
`{name, type}` and drops every other field (`lambdas/api/routes/athena.py`), so they are not
observable through the browser at all. Reading them needs a direct `athena:GetQueryResults`,
which the capturing session could not make.

So this fixture confirms that `Type` is bare `decimal`; it does **not** confirm that Athena
populates the sibling fields. The evidence for that is AWS's own SDK for pandas, which reads
`c["Precision"]` unconditionally for a decimal, and the API reference documenting both fields as
"For `DECIMAL` data types". If that were wrong, `athena_type_of` refuses the column rather than
guessing a scale — the safe direction — and every decimal conversion would fail loudly rather
than silently round. It is recorded as owed in `docs/testing/owed.md`.

## Regenerating it

Run the SQL in `test_rc_convert.py`'s `EVERY_TYPE` shape through the Query workspace, then use
*Save results to my files* — the synchronous CSV path, which copies the result object Athena
wrote rather than re-serialising it — and download the result. The types come from the results
response, which is `ColumnInfo` verbatim.
