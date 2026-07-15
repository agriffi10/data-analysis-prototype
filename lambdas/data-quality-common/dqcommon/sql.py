"""Athena SQL generation for the data-quality checks (SPEC-111 fills this in).

Stubbed namespace (SPEC-108 skeleton). Will hold:
  - the temp external-table DDL (typed table over the source; + the single-column
    raw-line table for CSV ragged detection, LazySimpleSerDe with a \001 delimiter that
    cannot occur in the data, so each physical line is one raw string);
  - the ONE profile query computing every exact check (per-column TRY_CAST type
    consistency, null/blank ratios, per-file + total row counts via $path);
  - the SEPARATE duplicate-rows query (GROUP BY <every column> HAVING COUNT(*) > 1 is a
    full shuffle — the single most expensive operation Athena offers — so it runs on its
    own and degrades to `duplicates: not_computed` rather than failing the whole check);
  - temp-table naming: dq_tmp_{hex32} (the request UUID with hyphens stripped). NOT
    _dq_{requestId}: a leading underscore needs backticks and a raw UUID's hyphens parse
    as subtraction, so the original form simply would not run.
  - the JSON SerDe choice: HIVE, not OpenX. AWS warns OpenX "can be non-deterministic…
    unexpected null values when none are present", and this arc's entire JSON story rests
    on "a null means the key was missing".
"""
