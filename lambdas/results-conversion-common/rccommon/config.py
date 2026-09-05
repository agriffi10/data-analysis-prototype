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
  CONVERTER_MEMORY_MB: PROVISIONAL. The memory the converter verb is expected to be sized at;
    the spec that builds the converter re-derives it and the cap below in the same test.
  CONVERTER_EPHEMERAL_MB: PROVISIONAL, for the same reason. The scratch disk the converter is
    expected to hold the result object and the written file on at once.
  CONVERTER_EXPANSION: PROVISIONAL. Bytes of in-memory frame the converter is assumed to need
    per byte of CSV read.
  RESULTS_MAX_BYTES: The largest result object this plane converts. Computed by a test against
    the three provisional budgets above, never a free number.
  MACHINE_TIMEOUT_SECONDS: The state machine's own ceiling, mirrored from the module's
    ``locals.tf`` because ASL cannot import Python. A test holds the two equal, and the timeout
    notification words this number rather than a sentence that can drift from it.
  PROTECTED_DESTINATIONS: Every folder name refused as a destination, at any depth in either
    space bucket: the three app-managed folders ``cpcommon.app_managed`` enumerates, plus the
    portal's own non-moving folders. Held equal, as a set, to the picker-locked list the browser
    and the file-operations plane refuse, so this plane cannot accept a destination the picker
    never offers.
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

CONVERTER_EXPANSION = 4

RESULTS_MAX_BYTES = 1024**3

MACHINE_TIMEOUT_SECONDS = 3600

PROTECTED_DESTINATIONS = (
    *_app_managed.SPACE_FOLDERS,
    "user_settings",
    "_data-quality-reports",
    "_directory",
    "_config",
)
