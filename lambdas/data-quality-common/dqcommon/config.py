"""Data-quality domain configuration.

Two kinds of value, and the split is settled. Per-deployment values — queue URLs, the workgroup
name, bucket names, the Cognito pair — are environment variables validated at import, and they
live in ``cpcommon.config``; do not re-declare them here. The tuning caps below are module
constants, because they are product decisions rather than deployment knobs: changing one changes
what the report means, so it should be a reviewed code change rather than a per-environment
variable somebody can drift.

Sizing evidence for the scan budget and the sample floor is in ``lambdas/info/planes/data-quality.md``.

Attributes:
  RESERVED_PREFIXES: First-path-segment prefixes a report may not be written under and a check
    may not target — Athena query output, the notification inbox and saved queries,
    table-share's copy destinations, this arc's own reports, the file-converter's scratch
    prefix, and the published username directory. Keep in sync with the file-converter arc's
    own blocklist: the two lists exist separately because the arcs are independent, and they
    must not drift apart. That scratch prefix is included defensively — this arc never writes
    it, but a check must not treat a sibling pipeline's scratch space as a valid destination
    either.
  MARKER_BASENAME: The space prefix marker that must never be overwritten.
  DQ_MAX_OBJECTS: Max objects under the target location. There is deliberately no maximum total
    size: that ceiling was a Lambda artefact, and Athena reads the data now.
  DQ_MAX_GZIP_OBJECT_BYTES: Max size of a single compressed source object. The one place a byte
    count still matters on the Athena path, and not about memory: gzip is not splittable, so one
    large compressed file is processed by exactly one worker no matter how much the engine
    parallelises, and simply runs until the DML query timeout kills it. Failing here in seconds,
    telling the user to decompress or split, beats failing at minute thirty. There is
    deliberately no equivalent cap on uncompressed objects, which Athena splits across workers.
  DQ_MAX_PARTITION_VALUES: Max observed values per detected partition key, bounding both the
    manifest and the projection DDL's enum list. At the current defaults this guard is
    unreachable, because a partition value only exists if an object sits under it, so breaching
    it means breaching the object cap first. It goes live the moment the object cap is raised
    above it, which is exactly why it is kept: the projection enum needs a ceiling that does not
    depend on a sibling constant nobody remembered to look at. A test pins the relationship.
  EXT_FORMAT: Extension to canonical format. Deliberately different from table-builder's map in
    two ways, both decisions for this arc rather than inherited behaviour: plain text is treated
    as CSV, and Parquet is accepted because the convert-then-verify workflow is the natural one
    and rejecting it would leave the two arcs unable to talk to each other.
  GZIP_SUFFIX: The compressed-object suffix. Compressed Parquet is rejected rather than
    half-supported — Athena cannot read it and its footer cannot be range-read through gzip.
  DQ_MAX_COLUMNS: The profile query's column ceiling. Several casts and aggregates per column
    approach Athena's query-string cap on a very wide table, so a wider source is rejected with
    a clear message rather than emitting an unparseable query.
  DQ_MAX_QUERY_BYTES: Athena's hard cap on a query string. Not a tuning knob but the engine's
    documented limit, named here so the builders can check themselves against it rather than
    repeating a magic number. Athena rejects an over-length statement after every bit of
    inspection work has been paid for, which is why the checks are on the rendered length rather
    than on a proxy like the file or column count.
  DQ_TYPE_DOMINANCE_THRESHOLD: The share of a column's non-null values its dominant parseable
    type must cover for the stragglers to be reported. A column that is almost all integers with
    a handful of placeholders has a real problem worth flagging; one that is 40% integers is not
    a broken numeric column but free text containing some numbers, and reporting most of its
    values as offending would be noise. Below the threshold the column is reported as text with
    no issue.
  DQ_OFFENDING_VALUE_SAMPLE: How many non-parsing values the profile query keeps per column. The
    aggregate collecting them must be bounded — a naive collect-then-truncate accumulates every
    row, which on a large source with a badly-typed column is the whole column in memory.
  DQ_QUERY_POLL_SECONDS: The Step Function's wait between query polls. Declared here so the
    constant and the state machine cannot drift; the template carries the same number with a
    pointer back to this line.
  DQ_SCAN_TOTAL_BYTES: The byte-scan budget, per request and never per file, divided across the
    manifest's files. Every encoding figure is labelled sampled with its coverage percentage.
  DQ_SCAN_HEAD_FRACTION: The share of a file's budget spent on a contiguous head window, because
    corruption clusters at the start of a badly-exported file — a byte-order mark, a
    codepage-encoded header row, an accented name in the first records.
  DQ_SCAN_SAMPLE_COUNT: How many evenly-placed ranged reads spend the rest of a file's share, so
    corruption confined to the middle or tail is still reachable.
  DQ_SCAN_MIN_SAMPLE_BYTES: The floor that makes the sample count an "up to" rather than an
    "always". Load-bearing for the timeout even though the byte budget is already safe: requests
    cost too, and a flat head-plus-samples per file would be tens of thousands of sequential
    reads on a large manifest.
  DQ_TOP_ISSUES: How many human-readable issues the report renders for the notification body.
    The notification is a sentence or two, not a report: past a handful the user stops reading
    and the real finding is buried. The full detail is in the report object.
  DQ_OFFSET_SAMPLE: How many invalid-sequence byte offsets the report keeps as examples. The
    count is the finding; the offsets exist so an operator can go and look at one. It also
    bounds memory — a mis-encoded large export contains tens of millions of invalid sequences,
    and retaining an offset for each would exhaust the function on precisely the file the check
    exists to diagnose.
  DQ_SCAN_READ_CHUNK_BYTES: Bytes pulled from a stream at a time. Peak memory is this, not the
    budget: the decode is streaming, so a large head window is never held whole, and without
    that property the budget would exhaust the function.
  DQ_INDEX_MAX_ENTRIES: Entries kept in a space's runs index, oldest dropped first. The cap is
    what keeps the index worth having — the dashboard fetches the whole file on every load, so
    an uncapped index makes the page slower the more the feature is used, which is the exact
    failure the index was introduced to avoid. 200 rows is 20 pages at 10 a page; past that a
    user wants a search, not a longer list.
"""

from cpcommon.app_managed import ATHENA_RESULTS_FOLDER, SHARED_TABLES_FOLDER

RESERVED_PREFIXES = frozenset(
    {
        ATHENA_RESULTS_FOLDER,
        "user_settings",
        SHARED_TABLES_FOLDER,
        "_data-quality-reports",
        "_fc-work",
        "_directory",
    }
)

MARKER_BASENAME = "DO_NOT_DELETE.txt"

DQ_MAX_OBJECTS = 1000

DQ_MAX_GZIP_OBJECT_BYTES = 1 * 1024**3

DQ_MAX_PARTITION_VALUES = 1000

EXT_FORMAT = {
    ".csv": "csv",
    ".txt": "csv",
    ".json": "json",
    ".ndjson": "json",
    ".jsonl": "json",
    ".parquet": "parquet",
}

GZIP_SUFFIX = ".gz"


def is_compressed(key: str) -> bool:
    """Reports whether an object key names a gzip-wrapped object.

    Shared rather than per-verb, and case-insensitive, because the two readings must never
    drift: inspect-source lowercases before classifying, so a case-sensitive test anywhere
    downstream would let a gzip object through as plain text. Reading compressed bytes as text
    yields roughly forty fabricated invalid-encoding findings per hundred bytes — a confident,
    entirely false corruption report over a file that is fine, on exactly the tooling population
    that produces both uppercase extensions and the codepage files the check is for.

    Args:
      key: The object key.

    Returns:
      True when the key ends in the gzip suffix, in any case.

    Raises:
      None.
    """
    return key.lower().endswith(GZIP_SUFFIX)


def _validate_caps() -> None:
    """Fails fast at import if a cap was edited into something meaningless.

    The caps are module constants rather than environment variables, so they change by reviewed
    code edit — this guards that edit. A cap of zero or a negative number would otherwise
    surface as an inexplicable terminal failure on every request instead of a cold-start error.
    The two ratios are validated separately: one outside its range would make every column
    either always-flagged or never-flagged, which looks like a broken checker rather than a
    broken config, and the other would either spend nothing on the head window or spend the
    whole share there — both silently changing what "sampled" means in a user's report.

    The call sits at the very BOTTOM of this module, and must stay there: it reads every cap,
    including the ones declared after its own ``def``. Moving the call up — the obvious tidy —
    is a NameError at cold start on every verb that imports this module.

    Args:
      None.

    Returns:
      None.

    Raises:
      RuntimeError: When any count is not a positive integer, or either ratio is not a float in
        the open-closed unit interval.
    """
    for name, value in (
        ("DQ_MAX_OBJECTS", DQ_MAX_OBJECTS),
        ("DQ_MAX_GZIP_OBJECT_BYTES", DQ_MAX_GZIP_OBJECT_BYTES),
        ("DQ_MAX_PARTITION_VALUES", DQ_MAX_PARTITION_VALUES),
        ("DQ_MAX_COLUMNS", DQ_MAX_COLUMNS),
        ("DQ_MAX_QUERY_BYTES", DQ_MAX_QUERY_BYTES),
        ("DQ_SCAN_TOTAL_BYTES", DQ_SCAN_TOTAL_BYTES),
        ("DQ_SCAN_SAMPLE_COUNT", DQ_SCAN_SAMPLE_COUNT),
        ("DQ_SCAN_MIN_SAMPLE_BYTES", DQ_SCAN_MIN_SAMPLE_BYTES),
        ("DQ_TOP_ISSUES", DQ_TOP_ISSUES),
        ("DQ_OFFSET_SAMPLE", DQ_OFFSET_SAMPLE),
        ("DQ_SCAN_READ_CHUNK_BYTES", DQ_SCAN_READ_CHUNK_BYTES),
        ("DQ_OFFENDING_VALUE_SAMPLE", DQ_OFFENDING_VALUE_SAMPLE),
        ("DQ_QUERY_POLL_SECONDS", DQ_QUERY_POLL_SECONDS),
        ("DQ_INDEX_MAX_ENTRIES", DQ_INDEX_MAX_ENTRIES),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise RuntimeError(f"dqcommon.config.{name} must be a positive int, got {value!r}")

    for name, ratio in (
        ("DQ_TYPE_DOMINANCE_THRESHOLD", DQ_TYPE_DOMINANCE_THRESHOLD),
        ("DQ_SCAN_HEAD_FRACTION", DQ_SCAN_HEAD_FRACTION),
    ):
        if not isinstance(ratio, float) or not 0 < ratio <= 1:
            raise RuntimeError(
                f"dqcommon.config.{name} must be a float in (0, 1], got {ratio!r}"
            )


DQ_MAX_COLUMNS = 200

DQ_MAX_QUERY_BYTES = 262_144

DQ_TYPE_DOMINANCE_THRESHOLD = 0.90

DQ_OFFENDING_VALUE_SAMPLE = 10

DQ_QUERY_POLL_SECONDS = 30

DQ_SCAN_TOTAL_BYTES = 2 * 1024**3

DQ_SCAN_HEAD_FRACTION = 0.5
DQ_SCAN_SAMPLE_COUNT = 20

DQ_SCAN_MIN_SAMPLE_BYTES = 4 * 1024**2

DQ_TOP_ISSUES = 5

DQ_OFFSET_SAMPLE = 10

DQ_SCAN_READ_CHUNK_BYTES = 256 * 1024

DQ_INDEX_MAX_ENTRIES = 200



_validate_caps()
