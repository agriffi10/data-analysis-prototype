# Spec: Ragged Rows Counted Per File, Not Against the Union

**ID:** SPEC-142
**Status:** Completed
**Last Updated:** 2026-08-03
**Depends On:** SPEC-110 (the manifest this reads), SPEC-112 (the ragged + cross-file checks), SPEC-114 (the report the numbers land in)

## Overview

On a folder whose CSV files disagree about their columns, the data-quality report shows a
ragged-row count that is fabricated. The check compares every physical line against the **union**
column count across all files, so every data row of a narrower file is counted ragged — and so is
**every file's header**, because a header only has the union's field count when the files already
agree.

The user therefore sees one underlying problem reported twice: once correctly, as cross-file column
disagreement naming the odd file out, and once again as a large ragged-row number that describes
nothing real. The second number is the more alarming of the two, and it is the wrong one.

This is the arc's own stated principle failing in the other direction. `report.py` is explicit that
"a green result the data did not earn is worse than no result"; a **red** result the data did not
earn is the same defect wearing different clothes.

The fix is to compare each line against the column count of **the file it came from**.

## Scope

### In Scope

- `dqcommon.sql.build_ragged_query` comparing per-file expected counts, keyed on Athena's `"$path"`.
- `dq_start_profile_query` passing the per-file counts the manifest already carries, instead of
  `len(union_columns(...))`.
- A guard on the rendered query size, with an honest `not_computed` when it cannot be met.
- Defined behaviour for a scanned path absent from the manifest.
- Regression coverage for the exact reported scenario.

### Out of Scope

- **The cross-file disagreement check itself** (`report.cross_file`). It is correct, it already
  names the minority file, and it remains the single source of truth for "these files disagree."
  This spec stops ragged rows from restating it, and changes nothing about it.
- **The two documented approximations** in the ragged count — `split(line, ',')` over-reporting on
  a quoted comma and on an embedded newline in a quoted field. Both are inherent to splitting a raw
  line, both are already labelled in the report, and neither is what this spec is about. The count
  stays `approximate` and keeps its note.
- **The union for every other purpose.** `union_columns` is correct for the external table's schema
  and for the profile query — a column present in only some files still has to be readable. Only
  the ragged comparison was wrong to use it.
- Non-CSV formats. JSON and Parquet have no raw-line table and no ragged concept; that path already
  returns `skipped` and is untouched.

---

## Functional Requirements

### FR-001: Each line is compared against its own file's column count

#### Description

`build_ragged_query` takes a mapping of S3 path → that file's header column count, and compares
each raw line's field count against the entry for the path it came from. Athena exposes the source
object as the `"$path"` pseudo-column on a Hive external table, which is what makes this possible
without a second scan.

The manifest already carries everything needed: `dq_inspect_source` writes
`{"key": …, "size": …, "columns": […]}` per file, so the expected count for a file is
`len(entry["columns"])`.

#### Acceptance Criteria

- [ ] On a folder where **all** files agree, the emitted count is identical to today's — this fix
      must be invisible on the common path.
- [ ] On a folder where files disagree, a data row is counted ragged **only** if its field count
      differs from its own file's header count.
- [ ] `dq_start_profile_query` no longer passes `len(columns)` (the union) to the ragged query.
- [ ] The golden-string tests in `test_sql_dqcommon.py` assert the exact new SQL, per the module's
      existing convention that a subtly wrong query does not crash — it reports wrong numbers about
      a user's data.

### FR-002: No header is ever counted ragged

#### Description

This falls out of FR-001 rather than needing its own filter — a header has exactly its own file's
column count by definition — but it is the half of the bug users actually notice, so it is asserted
directly rather than assumed.

The docstring at `sql.py` currently states the header "has exactly `header_column_count` fields by
definition, so it is never ragged." That is true per file and false against a union; it must be
corrected to say which.

#### Acceptance Criteria

- [ ] A folder of two files with different column counts reports **zero** ragged rows when every
      data row matches its own header.
- [ ] `total_lines` still counts every non-blank line including headers — it is named for lines,
      not rows, and that does not change.
- [ ] The corrected reasoning is in the docstring, naming the union as the case that broke it.

### FR-003: The query-size guard

#### Description

A per-path comparison means one branch per file in the rendered SQL. `DQ_MAX_OBJECTS` is 1000 and
S3 keys can be long, so the statement can grow large; Athena caps a query string at 256 KB.

A guard that silently truncated the mapping would produce exactly this spec's bug again, on a
subset. It must refuse instead.

#### Acceptance Criteria

- [ ] The guard is on the **rendered length** of the query against a named constant, not on a magic
      file count — file count is a poor proxy for key length.
- [ ] When the guard trips, ragged is reported `not_computed` with a user-facing reason, following
      the existing `NOT_COMPUTED_RAGGED` wording pattern (SPEC-106: no raw engine text).
- [ ] The rest of the report still lands — a ragged figure that cannot be computed never fails the
      run, consistent with SPEC-111 FR-003.
- [ ] A test proves the trip, by constructing a manifest with keys long enough to breach it rather
      than by monkey-patching the constant.

### FR-004: A scanned path absent from the manifest

#### Description

The raw-line table scans the folder; the mapping comes from the manifest. If an object appears in
the scan with no manifest entry, there is no expected count for it and no basis on which to judge
its lines.

#### Acceptance Criteria

- [ ] Such lines are excluded from the ragged **numerator** — an unjudgeable line is never counted
      as ragged.
- [ ] The behaviour is stated in the docstring so the next reader does not read the `ELSE` branch as
      an oversight.
- [ ] A test covers a path present in the scan but not the manifest.

### FR-005: One cause, one finding

#### Description

The user-visible outcome this spec exists to produce: a folder whose files disagree yields the
cross-file finding, and **not** a second contradictory ragged number describing the same thing.

#### Acceptance Criteria

- [ ] A regression test reproduces the reported scenario — a folder whose files disagree about
      columns, where every row is well-formed within its own file — and asserts a ragged count of
      zero alongside a populated `crossFile` finding.
- [ ] The test is named for the bug so a future reader understands what it pins.

---

## Data Model

No stored shape changes. The query builder's signature changes from a scalar to a mapping:

```python
# dqcommon/sql.py
def build_ragged_query(
    database: str,
    raw_table_name_: str,
    expected_by_path: dict[str, int],   # was: header_column_count: int
) -> str: ...
```

`expected_by_path` is keyed by the full `s3://bucket/key` form that `"$path"` returns, built from
the manifest's `key` plus the request's bucket. The rendered comparison is a `CASE` over `"$path"`:

```sql
SELECT COUNT_IF(
         <present>
         AND CASE "$path"
               WHEN 's3://…/a.csv' THEN cardinality(split(line, ',')) <> 3
               WHEN 's3://…/b.csv' THEN cardinality(split(line, ',')) <> 5
               ELSE false            -- FR-004: unjudgeable, never ragged
             END
       ) AS ragged_rows,
       COUNT_IF(<present>) AS total_lines
FROM …
```

## Implementation Phases

### Phase 1: The query builder

- Change `build_ragged_query` to take `expected_by_path` and render the `CASE`.
- Add the size guard and its constant.
- Correct the docstring's header claim, naming the union as what broke it.
- Update the golden-string tests.

### Phase 2: The caller

- Build the mapping in `dq_start_profile_query` from the manifest, keyed to the `"$path"` form.
- Handle the guard's refusal into the existing `not_computed` block.

### Phase 3: Regression coverage

- The FR-005 test reproducing the reported scenario end to end through `report.build`.
- The FR-003 and FR-004 tests.

### Phase 4: Verify against real data

- Run a data-quality check from the UI on a folder whose files deliberately disagree, and confirm
  the report shows the cross-file finding **without** a fabricated ragged count.
- A folder whose files agree must produce the same numbers as before the change.
