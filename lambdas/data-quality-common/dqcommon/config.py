"""Data-quality domain configuration (SPEC-108 FR-003).

Config style for this arc, settled here:

- **Per-deployment values** (queue URLs, the workgroup name, bucket names, the Cognito
  pair) are ENV VARS validated at import — and they live in ``cpcommon.config``, whose
  ``_require`` fail-fast runs at cold start for every verb that attaches the layer
  (SPEC-083 FR-001 / SPEC-107 FR-001). Do not re-declare them here.
- **``DQ_*`` tuning caps are MODULE CONSTANTS here.** They are product decisions, not
  deployment knobs: changing one changes what the report means, so it should be a
  reviewed code change rather than a per-environment env var somebody can drift.

The constants below are declared in the foundation so the later specs share one source;
each is consumed by the spec named against it.
"""

# SPEC-109 — where a report may NOT be written, and where a check may not target.
#
# The report destination ({space}/_data-quality-reports/{requestId}/) must resolve inside
# the requesting space and must not collide with any of these first-path-segment prefixes.
#
# KEEP IN SYNC with the file-converter arc's reserved-prefix blocklist (SPEC-116). The two
# lists exist separately because the arcs are independent, and they must not drift apart —
# if you add a prefix here, add it there. `_fc-work/` is the file-converter's scratch
# prefix, included here DEFENSIVELY: this arc never writes it, but a check must not treat
# the sibling pipeline's scratch space as a valid destination either.
RESERVED_PREFIXES = frozenset(
    {
        "athenaresults",          # Athena query output (SPEC-032)
        "user_settings",          # the notification inbox + saved queries (SPEC-058/043)
        "shared_tables",          # table-share copy destinations (SPEC-088)
        "_data-quality-reports",  # this arc's own reports
        "_fc-work",               # the file-converter's scratch prefix (SPEC-116)
    }
)

#: The space prefix marker that must never be overwritten (SPEC-014).
MARKER_BASENAME = "DO_NOT_DELETE.txt"

# SPEC-110 — source inspection caps.
# Max objects under the target location. Mirrors tscommon's SHARE_MAX_OBJECTS. There is
# deliberately NO max total size: that ceiling was a Lambda artefact, and Athena — not a
# Lambda — reads the data now.
DQ_MAX_OBJECTS = 1000

# Max size of a single COMPRESSED (.gz) source object.
#
# The one place a byte count still matters on the Athena path, and it is not about memory:
# gzip is NOT SPLITTABLE. A single large .csv.gz is processed by EXACTLY ONE Athena worker
# no matter how much the engine parallelizes, so it simply runs until the 30-minute DML
# query timeout (an account quota — architecture §7.2) kills it. Failing here, in seconds,
# telling the user to decompress or split the file, is strictly better than failing at
# minute 30 with query_timeout. There is deliberately NO equivalent cap on UNCOMPRESSED
# objects: Athena splits those across workers, which is the whole point of this design.
DQ_MAX_GZIP_OBJECT_BYTES = 1 * 1024**3  # 1 GiB

# Max OBSERVED values per detected partition key. Bounds two things at once: the manifest
# (which records the values) and SPEC-111's partition-projection DDL (whose enum lists
# them).
#
# NOTE, and check this before tuning either cap: at these defaults this guard is
# UNREACHABLE. A partition value only exists because at least one object sits under it,
# so N distinct values imply >= N objects — and with this cap equal to DQ_MAX_OBJECTS,
# breaching it means breaching the object cap first, which raises too_many_files. The
# guard goes LIVE the moment DQ_MAX_OBJECTS is raised above it (or this is lowered), which
# is exactly why it is kept rather than deleted: the projection enum needs a ceiling that
# does not depend on a sibling constant nobody remembered to look at.
# test_the_object_cap_dominates_the_partition_value_cap_at_the_defaults pins the relationship.
DQ_MAX_PARTITION_VALUES = 1000

# Extension → canonical format (SPEC-110 FR-002).
#
# DELIBERATELY DIFFERENT from table-builder's map (table-builder-inspect-source/
# inspect_source.py:22-28) in two ways — both new decisions for this arc, not inherited
# behaviour, so neither should be "corrected" back into line:
#
#   .txt   — absent from table-builder's map; treated as CSV here.
#   .parquet — the convert-then-verify workflow is the natural one (run the file converter
#              on a messy CSV, then check the resulting Parquet). Rejecting Parquet as
#              "out of scope for a quality checker" would leave the two arcs unable to
#              talk to each other, so this must not be dropped.
EXT_FORMAT = {
    ".csv": "csv",
    ".txt": "csv",
    ".json": "json",
    ".ndjson": "json",
    ".jsonl": "json",
    ".parquet": "parquet",
}

#: Extensions that are never readable through a gzip wrapper (see ``classify`` in the verb).
#: .parquet.gz is unreadable by Athena AND un-probeable by polars (the footer can't be
#: range-read through gzip), so it is rejected rather than half-supported.
GZIP_SUFFIX = ".gz"


def _validate_caps() -> None:
    """Fail fast at import if a cap was edited into something meaningless.

    The DQ_* caps are module constants rather than env vars (see the header): they are
    product decisions, so they change by reviewed code edit. This guards that edit —
    lambdas.md §6 wants caps validated at init, and a cap of 0 or -1 would otherwise
    surface as an inexplicable terminal on every request instead of a cold-start error.
    """
    for name, value in (
        ("DQ_MAX_OBJECTS", DQ_MAX_OBJECTS),
        ("DQ_MAX_GZIP_OBJECT_BYTES", DQ_MAX_GZIP_OBJECT_BYTES),
        ("DQ_MAX_PARTITION_VALUES", DQ_MAX_PARTITION_VALUES),
        ("DQ_MAX_COLUMNS", DQ_MAX_COLUMNS),
        ("DQ_SCAN_TOTAL_BYTES", DQ_SCAN_TOTAL_BYTES),
        ("DQ_OFFENDING_VALUE_SAMPLE", DQ_OFFENDING_VALUE_SAMPLE),
        ("DQ_QUERY_POLL_SECONDS", DQ_QUERY_POLL_SECONDS),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise RuntimeError(f"dqcommon.config.{name} must be a positive int, got {value!r}")

    # A ratio, not a count — validated separately. A threshold outside (0, 1] would make
    # every column either always-flagged or never-flagged, which looks like a broken
    # checker rather than a broken config.
    if not isinstance(DQ_TYPE_DOMINANCE_THRESHOLD, float) or not 0 < DQ_TYPE_DOMINANCE_THRESHOLD <= 1:
        raise RuntimeError(
            "dqcommon.config.DQ_TYPE_DOMINANCE_THRESHOLD must be a float in (0, 1], "
            f"got {DQ_TYPE_DOMINANCE_THRESHOLD!r}"
        )

# SPEC-111 — the profile query's column ceiling.
# Athena caps a query STRING at 262,144 bytes. Four TRY_CASTs plus a null-ratio and a
# sample aggregate per column approaches that on a very wide table, so a source wider
# than this is rejected with a clear message rather than emitting an unparseable query.
DQ_MAX_COLUMNS = 200

# SPEC-111 — a column's dominant parseable type must cover at least this share of its
# NON-NULL values for the stragglers to be reported as a type-consistency issue.
#
# The shape of the judgement: a column that is 99% integers with a handful of "N/A"s has
# a real problem worth flagging. A column that is 40% integers is not a broken numeric
# column, it is free text that happens to contain some numbers — reporting 60% of its
# values as "offending" would be noise. Below the threshold the column is reported as
# `text` with NO issue.
DQ_TYPE_DOMINANCE_THRESHOLD = 0.90

# SPEC-111 — how many non-parsing values the profile query keeps as examples, per column.
#
# The aggregate that collects them MUST be bounded (dqcommon.sql uses Trino's n-ary
# max_by, whose accumulator holds only N values). A naive array_agg-then-truncate
# accumulates O(rows) — on a 250 GB source with a badly-typed column that is the whole
# column in memory, which fails the query rather than sampling it.
DQ_OFFENDING_VALUE_SAMPLE = 10

# SPEC-111 — the Step Function's Wait interval between GetQueryExecution polls.
# Declared here so the constant and the state machine's Wait cannot drift; the ASL
# template carries the same number with a pointer back to this line.
DQ_QUERY_POLL_SECONDS = 30

# SPEC-112 — the byte-scan budget, PER REQUEST (never per file).
# Divided across the files in the manifest; every encoding figure is labelled sampled
# with its coverage percentage. v3 bounded this PER FILE (256 MiB x up to 1000 files
# ~= 276 GB through one 1024 MB Lambda in 300 s ~= 920 MB/s sustained, against a
# real-world ~60-100 MB/s) — it would have passed on a three-file fixture and timed out
# in production. That is the exact error class this arc's re-architecture exists to
# eliminate, so the budget is per REQUEST.
DQ_SCAN_TOTAL_BYTES = 2 * 1024**3  # 2 GiB


# Called at the BOTTOM: it reads every cap above, including the two declared after its
# own def.
_validate_caps()
