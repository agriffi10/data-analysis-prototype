"""The results-conversion plane's constants: vocabularies, caps and the refused destinations.

Attributes:
  SPACE_KINDS: The two space kinds. The kind decides which bucket a destination resolves in.
  FORMATS: The closed set of output formats. CSV is deliberately absent — the CSV Athena wrote
    is copied by the synchronous path, and this plane never re-serialises it.
  FORMAT_LABELS: How each format is named to a user.
  ON_CONFLICT: The two answers to a name already taken at the destination.
  MAX_FILENAME_BYTES: The longest file name accepted, in UTF-8 bytes — S3's own key-segment
    ceiling as the browser applies it.
  MAX_PREFIX_BYTES: The longest destination folder accepted, in UTF-8 bytes — S3's key ceiling.
  CONVERTER_MEMORY_MB: The converter verb's memory, mirrored from the module's ``locals.tf``.
    **3,008 MB is this ACCOUNT's ceiling, not Lambda's.** Lambda documents 10,240 MB, and
    `CreateFunction` refused it here with ``'MemorySize' value failed to satisfy constraint:
    Member must have value less than or equal to 3008`` — the un-raised quota an account keeps
    until someone asks AWS to lift it. Nothing local can see that: `tofu validate` passes, the
    module's own range check passes, and the plan is green. It is only the apply that knows.
  CONVERTER_EPHEMERAL_MB: Its scratch disk, which holds the downloaded result object and the
    written file at the same time. Lambda's documented range reaches 10,240 MB and this asks for
    2,048, which is the largest this account is KNOWN to accept rather than the largest it might:
    every other function in the fleet runs at the 512 MB default, so 2,048 is proven by this
    converter alone and everything above it is untested. Asking for more and meeting a second
    quota refusal costs a red trunk, which is worth more than the caps this gives up.
  CONVERTER_TIMEOUT_SECONDS: Its execution ceiling, likewise mirrored.
  DISK_RESERVE / MEMORY_RESERVE: The fraction of each the budget does NOT spend, so the
    converter is not sized to fill a disk exactly or to run at the edge of an OOM.
  OUTPUT_EXPANSION: MEASURED bytes of output per byte of CSV, per format — the worst figure
    observed across the fixture sizes, not the average.
  EXCEL_MAX_ROWS: Excel's own data-row ceiling — one less than its 1,048,576 rows, because the
    header takes one. Declared here rather than in the converter because the cell cap below is
    derived from it: the per-row cost is paid on every admitted row.
  EXCEL_BASELINE_MB: The Excel path's fixed cost, in MiB as every ``_MB`` here is: the peak a
    conversion of no cells would reach. It is the largest local fixed cost of any shape plus the
    gap one production run showed over the same input run locally — the 490,000-row run's own
    query, rebuilt to the byte — which comes to 249.2, rounded up to the next ten. That gap is not
    a constant, so this is not a production measurement: the conversion at the cell cap sat
    several times further above its local peak, and two production readings of different shapes
    cannot say how much of a gap is fixed and how much is spent per cell.
  EXCEL_PEAK_BYTES_PER_CELL: MEASURED peak bytes per cell for the Excel path, net of the per-row
    term. Excel's peak is set by CELLS, not bytes: polars hands xlsxwriter a Python copy of
    every cell and xlsxwriter stores every cell again before it writes, so a NULL — one byte of
    CSV — costs about 250 bytes of memory. The shape that binds this is unique 20-character text
    at 15 columns, 498 bytes a cell less its 27-byte row share; rounded up to the next ten.
  EXCEL_PEAK_BYTES_PER_ROW: MEASURED peak bytes per row beyond the cells, from one column of
    one-character text against fifteen in the same run — 362 to 392 across the runs. Rounded up
    to the next ten.
  EXCEL_COVERED_BYTES_PER_CELL: The CSV width, in bytes per cell, of the shape that binds the
    per-cell figure, and so the widest cell that figure already pays for.
  EXCEL_PEAK_BYTES_PER_LONG_BYTE: MEASURED peak bytes per CSV byte beyond the covered width — the
    long-text term, which the corpus needs at no more than 6.1. Rounded up to a whole byte.
  EXCEL_MAX_CELLS: The largest result, in cells (rows times columns), converted to Excel: what
    the memory budget holds once the baseline and every admitted row's own cost are paid. It is
    derived from the constants above and the budget test recomputes it. The worst corner the
    caps admit — every admitted cell, every admitted row, the byte cap reached — carries no
    long-byte term, because the byte cap is set so that there is none there; fewer, longer
    cells pay it, but pay less in total, because a cell costs more than the bytes it covers.
  RESULTS_MAX_BYTES: The largest result object this plane converts, PER FORMAT. One number
    could not be honest: the streamed formats are bounded by the scratch disk and Excel by
    memory, which on this account's numbers puts them an order of magnitude apart — so a single
    cap would either starve Parquet and JSON or promise an Excel conversion that runs out of
    memory. Excel's is the smaller of the disk bound and the bytes its cell cap's cells are
    already paid for at the covered width. The numbers themselves are not restated here: they
    are derived below from the constants above and the budget test recomputes them, so a hand
    edit to either side is a red test and a figure copied into this prose is the one that would
    go stale.
  MAX_RESULT_COLUMNS: The widest result set this plane converts, in ANY format. Bounded by the
    transport rather than by a file format: the described columns travel on the Step Functions
    state, which is capped at 256 KB. Where that boundary falls depends on how wide a column
    entry is, and the range was measured rather than estimated: about 6,400 columns for a short
    name and a bare type, about 4,900 for a twenty-character name, and about 2,500 for a long
    name plus a decimal's precision and scale. The FLOOR is what this is set against, not the
    middle. Excel's own 16,384-column ceiling is two to three times past even the widest of
    those, so it cannot be reached here at all — which is why this plane has no
    ``excel_column_limit``: a refusal that can deny nobody reads as a fence to everyone
    downstream. At 1,500 the worst entry still uses under 60% of the limit.
  MEASURED_ON: What the numbers above were measured against, so a reader can re-measure rather
    than trust them. The Excel figures are the container's cgroup peak, which counts the page
    cache of the CSV and of xlsxwriter's temporary XML and so is the larger of the two measures;
    memory was measured on both architectures and agrees within 5% at matched sizes, while time
    under emulation is not used for anything. The cgroup slope moves by several percent from run
    to run, which is why the corpus is the maximum over every run and each constant sits above it.
    The corpus is local, and production's peak sat further above its local twin at the cell cap
    than at the 490,000-row shape, so no one offset fits both; the model bounded it there because
    each term is an envelope over every shape, not a fit to one. So a re-derivation is not validated by the budget test
    alone, but by reading the live conversion at the new cell cap in ``docs/testing/e2e.md``
    against the model's figure.
  MACHINE_TIMEOUT_SECONDS: The state machine's own ceiling, mirrored from the module's
    ``locals.tf`` because ASL cannot import Python. A test holds the two equal, and the timeout
    notification words this number rather than a sentence that can drift from it.
  PROTECTED_DESTINATIONS: Every folder name refused as a destination, at any depth in either
    space bucket: the three app-managed folders ``cpcommon.app_managed`` enumerates, the
    portal's own non-moving folders, and ``system_settings``. A SUPERSET of the picker-locked
    list the browser and the file-operations plane refuse, by rule and not by coincidence: this
    plane cannot accept a destination the picker never offers, and it may also refuse one the
    picker has no opinion about, because what it mirrors is the execution role's DENY.
    ``system_settings`` entered as exactly that second kind and no longer is — the picker locks
    it too now — but the reason it is here does not move with the picker: the role denies
    ``*/system_settings/*`` in both buckets, and the converter holds a write grant, so a
    destination inside it would reach the user as a bare ``AccessDenied`` instead of a named
    refusal. ``paths`` states the rule this follows — the validator mirrors the DENY, not the
    picker.
    The name comes from ``cpcommon.app_managed``, which owns it; spelling it here would be a
    second declaration, and the path sweep refuses one. This is a refusal list mirroring IAM, and
    nothing builds a key from it.
"""

from cpcommon import app_managed as _app_managed

from . import reasons

SPACE_KINDS = frozenset({"personal", "shared"})

FORMATS = frozenset({"parquet", "json", "xlsx"})

FORMAT_LABELS = {"parquet": "Parquet", "json": "JSON", "xlsx": "Excel"}

ON_CONFLICT = frozenset({"refuse", "overwrite"})

MAX_FILENAME_BYTES = 255

MAX_PREFIX_BYTES = 1024

CONVERTER_MEMORY_MB = 3_008

CONVERTER_EPHEMERAL_MB = 2_048

CONVERTER_TIMEOUT_SECONDS = 600

DISK_RESERVE = 0.10

MEMORY_RESERVE = 0.15

OUTPUT_EXPANSION = {"parquet": 0.252, "json": 1.481, "xlsx": 0.603}

EXCEL_MAX_ROWS = 1_048_575

EXCEL_BASELINE_MB = 250

EXCEL_PEAK_BYTES_PER_CELL = 480

EXCEL_PEAK_BYTES_PER_ROW = 400

EXCEL_COVERED_BYTES_PER_CELL = 23

EXCEL_PEAK_BYTES_PER_LONG_BYTE = 7

EXCEL_MAX_CELLS = 4_100_000

RESULTS_MAX_BYTES = {
    "parquet": 1472 * 1024**2,
    "json": 704 * 1024**2,
    "xlsx": 64 * 1024**2,
}

MAX_RESULT_COLUMNS = 1_500

MEASURED_ON = (
    "the fleet image built from lambdas/Dockerfile, polars 1.12.0 and xlsxwriter 3.2.9. Parquet "
    "and JSON over generated Athena-shaped CSVs of 7.2 MB, 14.6 MB, 29.2 MB and 58.6 MB; Excel by "
    "five runs over 23 generated shapes at two sizes each, on arm64 and amd64: two exploratory "
    "runs on an image built at 13bb7a30, which copied each CSV into /tmp through a bind mount and "
    "so charged a large file's page cache twice, and set most of the maxima; and three runs of "
    "scripts/measure_excel_peak.py on an image built from the commit that introduced these "
    "constants, which read each shape at or below them. Anchored to the converter's own REPORT "
    "lines of 2026-09-10: a 490,000 x 4 result at 933 MiB and a 1,048,575 x 15 one that timed out "
    "at 3,008"
)


def max_result_bytes(fmt: str) -> int:
    """Returns the largest result object this plane converts into one format.

    Args:
      fmt: The output format.

    Returns:
      The cap in bytes. An unknown format falls to the SMALLEST cap rather than the largest,
      because the caller that could pass one is a validator that has already failed.

    Raises:
      None.
    """
    return RESULTS_MAX_BYTES.get(fmt, min(RESULTS_MAX_BYTES.values()))


def excel_refusal(rows: int, columns: int) -> str | None:
    """Decides whether a result set is too big to become a workbook, from its shape alone.

    The one predicate the converter and the budget test both ask, so the guard measures what
    production refuses rather than a copy of it. It is asked before anything is materialised,
    because the materialisation is the thing that does not fit.

    The row ceiling is checked FIRST: a result over it is usually over the cell cap too, and
    "more than a spreadsheet can hold" is the truer of the two sentences for it.

    Args:
      rows: The result's data rows, counted from the CSV itself.
      columns: Its column count.

    Returns:
      ``reasons.EXCEL_ROW_LIMIT`` over Excel's row ceiling, ``reasons.EXCEL_CELL_LIMIT`` over the
      cell cap, and None otherwise. A result exactly at either limit is admitted.

    Raises:
      None.
    """
    if rows > EXCEL_MAX_ROWS:
        return reasons.EXCEL_ROW_LIMIT
    if rows * columns > EXCEL_MAX_CELLS:
        return reasons.EXCEL_CELL_LIMIT
    return None

MACHINE_TIMEOUT_SECONDS = 3600

PROTECTED_DESTINATIONS = (
    *_app_managed.SPACE_FOLDERS,
    "user_settings",
    "_data-quality-reports",
    "_directory",
    "_config",
    _app_managed.SYSTEM_SETTINGS_FOLDER,
)
