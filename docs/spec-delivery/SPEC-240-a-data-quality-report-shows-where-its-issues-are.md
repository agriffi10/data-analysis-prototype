# Completed Spec — SPEC-240: A Data-Quality Report Shows Where Its Issues Are

## What was completed?

A tester read a report saying a folder had duplicate rows and asked which rows they were. The
report could not say — it stored the count and nothing else, and it stored two further figures it
had never shown. All three are answered now.

- **Which rows repeat.** `sql.build_duplicates_query` keeps up to `DQ_DUPLICATE_SAMPLE` (5) of the
  most-repeated rows beside the count, through the n-ary `max_by` the offending-value samples
  already used, so nothing extra is scanned. `report.py` writes them as
  `exact.duplicateSamples`, and the page shows them under *Most repeated rows* with a
  *Times it appears* column, `NULL` and `(empty)` told apart as the Data Explorer tells them apart.
- **How many rows each file holds.** `exact.rowCountsByFile` has always been written and never
  rendered; it is now a closed *Rows in each file (N files)* disclosure, withheld below two entries
  because a single-file report's one count IS the report's row count.
- **Where the bad encoding is.** `approximate.encoding.sampleOffsets` likewise. Each example renders
  as a path relative to the checked folder plus its byte offset.
- **A type that was wrong the whole time.** `EncodingFigure.sampleOffsets` was `number[]`; the byte
  scan has always written `{key, offset}`. Nothing rendered the field, so nothing broke. The
  fixture now carries the writer's shape.

New symbols: `sql.grouped_column_names`, `sql.has_nested_column`, `sql.SAMPLE_VALUE_CHARS`;
`report.source_shape`, `report.duplicates_field_size_limit`, `report.SAMPLES_OMITTED_NESTED`,
`report.SAMPLES_OMITTED_TOO_LARGE`; `config.DQ_DUPLICATE_SAMPLE`, `config.DQ_REPORT_MAX_BYTES`;
`dq_assemble_report._serialize`, `_within_document_cap`, `OVER_CAP_EVENT`; the browser's
`DuplicateSamples` and `EncodingExample` types and `lambdas/test_data_quality_report_contract.py`.

### Deliberate deviations

- **`_projection`'s docstring was not corrected.** The spec said it claimed a test that did not
  exist. That premise carried two claims and both failed, differently: the `build_profile_query`
  half was **wrong when written** (a caller was already there at the spec's own read point, added
  by #812), and the `build_duplicates_query` half was **true then and went stale** when #824 created
  `test_sql_dqcommon.py`. The docstring is accurate today. The spec records both halves, because the
  useful lesson is that the grep was wrong, not that the code moved.
- **The duplicates size test asserts against a spelled-out `_ATHENA_QUERY_STRING_LIMIT`**, not
  `DQ_MAX_QUERY_BYTES` as the criterion said. Its neighbour already does this and says why: a guard
  measured against the setting passes however far a mistake raises it.
- **The omission sentences live in `report.py`, not `messages.py`** as the file list said.
  `messages.py` registers terminal reason codes; these are report prose, and sit beside
  `NOT_COMPUTED_DUPLICATES`.
- **No file is named per sample**, per the spec's own decision — grouping by every column erases it.
  The per-file row counts are the "where" at the file level.

## What changed from earlier specs?

- `EncodingFigure.sampleOffsets` (SPEC-113) is retyped `EncodingExample[]`. A type correction, not a
  behaviour change: the writer never emitted `number[]`.
- `report.parse_result` (SPEC-112) takes an optional `field_size_limit`; `dq_assemble_report._write`
  takes serialized bytes rather than a dict, with `_serialize` between them.
- `build_duplicates_query` (SPEC-112) builds its grouping from `grouped_column_names` rather than a
  second copy of the rule. Its statement is unchanged byte for byte for a source with a nested
  column, and its count, `GROUP BY` and `HAVING` clauses are unchanged for every source.
- `reportFixtures.ts` (SPEC-113) — `csvReport()`'s `sampleOffsets` now carries `{key, offset}`
  entries drawn from that fixture's own `rowCountsByFile`.

## Verification

Locally, by exit code: `ruff check`, `mypy` (154 files), `pytest lambdas/` (4,928 passed, coverage
91.46%), and the portal's `format:check`, `lint`, `test` (2,798 passed) and `build` — plus all nine
of `ci.yml`'s validators, including `validate_docs_test.py` and the three PR-queue corpora.
Two fresh-context diff reviews before the push: one against the acceptance criteria and the
rulebooks, one adversarial-execution pass that planted eighteen mutations in the new guards and
watched each redden.

Measured rather than asserted: the sampled duplicates statement renders **116,376 bytes** at
`DQ_MAX_COLUMNS` columns of 255 characters plus two partition keys, against Athena's 262,144 limit —
the profile query is 234,662 at the same shape, so the sampled statement is the smaller of the two.
**— Superseded in part: the profile query now cuts its offending values in the statement and keeps
five a column rather than ten, and measures 247,093 at that shape; the comparison still holds.**

**Deferred to a live run after deploy:** FR-003's last criterion. `docs/testing/e2e.md` §4.6 carries
it as three rows with their fixtures — the `dq_dupes/` counts and ordering, the per-file disclosure,
and the nested-column source whose count must survive losing its samples. **Ran 2026-09-21, all
three passed** (`docs/testing/sessions.md`, 2026-09-21 evening).
