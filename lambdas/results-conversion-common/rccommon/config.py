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
  CONVERTER_EPHEMERAL_MB: Its scratch disk, which holds the downloaded result object and the
    written file at the same time.
  CONVERTER_TIMEOUT_SECONDS: Its execution ceiling, likewise mirrored.
  DISK_RESERVE / MEMORY_RESERVE: The fraction of each the budget does NOT spend, so the
    converter is not sized to fill a disk exactly or to run at the edge of an OOM.
  OUTPUT_EXPANSION: MEASURED bytes of output per byte of CSV, per format — the worst figure
    observed across the fixture sizes, not the average.
  EXCEL_MEMORY_EXPANSION: MEASURED peak resident bytes per byte of CSV for the Excel path,
    again the worst observed. It is large because that path cannot stream: polars materialises
    the frame and xlsxwriter builds the whole workbook in memory beside it.
  RESULTS_MAX_BYTES: The largest result object this plane converts, PER FORMAT. One number
    could not be honest: the streamed formats are bounded by the scratch disk at about 3.6 GB,
    and Excel by memory at a tenth of that, so a single cap would either starve Parquet and
    JSON or promise an Excel conversion that runs out of memory. Held equal to what the budget
    test recomputes from the constants above, so a hand edit to either side is a red test.
  MAX_RESULT_COLUMNS: The widest result set this plane converts, in ANY format. Bounded by the
    transport rather than by a file format: the described columns travel on the Step Functions
    state, which is capped at 256 KB, and a realistic column entry puts that boundary at about
    4,900 columns — measured. Excel's own 16,384-column ceiling therefore cannot be reached
    here, which is why this plane has no ``excel_column_limit``: a refusal that can deny nobody
    reads as a fence to everyone downstream. Left at a third of the boundary so a wider entry —
    a long name, another per-column field — does not silently cross it.
  MEASURED_ON: What the numbers above were measured against, so a reader can re-measure rather
    than trust them.
  MACHINE_TIMEOUT_SECONDS: The state machine's own ceiling, mirrored from the module's
    ``locals.tf`` because ASL cannot import Python. A test holds the two equal, and the timeout
    notification words this number rather than a sentence that can drift from it.
  PROTECTED_DESTINATIONS: Every folder name refused as a destination, at any depth in either
    space bucket: the three app-managed folders ``cpcommon.app_managed`` enumerates, the
    portal's own non-moving folders, and ``system_settings``. A SUPERSET of the picker-locked
    list the browser and the file-operations plane refuse — this plane cannot accept a
    destination the picker never offers, and it also refuses one the picker has no opinion
    about but the execution role denies. ``system_settings`` is the second kind: the role
    denies ``*/system_settings/*`` in both buckets, so with a write grant in hand a destination
    inside it would reach the user as a bare ``AccessDenied`` instead of a named refusal.
    ``paths`` states the rule this follows — the validator mirrors the DENY, not the picker.
    It is a literal rather than a shared constant because no owner declares that name yet: it
    is a prefix three app-managed folders are moving under, and the spec doing that migration
    owns when it gains one. This is a refusal list mirroring IAM, and nothing builds a key
    from it.
"""

from cpcommon import app_managed as _app_managed

SPACE_KINDS = frozenset({"personal", "shared"})

FORMATS = frozenset({"parquet", "json", "xlsx"})

FORMAT_LABELS = {"parquet": "Parquet", "json": "JSON", "xlsx": "Excel"}

ON_CONFLICT = frozenset({"refuse", "overwrite"})

MAX_FILENAME_BYTES = 255

MAX_PREFIX_BYTES = 1024

CONVERTER_MEMORY_MB = 10_240

CONVERTER_EPHEMERAL_MB = 10_240

CONVERTER_TIMEOUT_SECONDS = 600

DISK_RESERVE = 0.10

MEMORY_RESERVE = 0.15

OUTPUT_EXPANSION = {"parquet": 0.252, "json": 1.481, "xlsx": 0.603}

EXCEL_MEMORY_EXPANSION = 32.45

RESULTS_MAX_BYTES = {
    "parquet": 7360 * 1024**2,
    "json": 3712 * 1024**2,
    "xlsx": 256 * 1024**2,
}

MAX_RESULT_COLUMNS = 1_500

MEASURED_ON = (
    "the fleet image built from lambdas/Dockerfile, polars 1.12.0 and xlsxwriter 3.2.9, over "
    "generated Athena-shaped CSVs of 7.2 MB, 14.6 MB, 29.2 MB and 58.6 MB"
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

MACHINE_TIMEOUT_SECONDS = 3600

PROTECTED_DESTINATIONS = (
    *_app_managed.SPACE_FOLDERS,
    "user_settings",
    "_data-quality-reports",
    "_directory",
    "_config",
    "system_settings",
)
