"""User-facing data-quality notification text and reason codes.

Registers this domain's reason codes with the shared registry, which gives a domain-scoped
resolver over the shared base table and — the part that matters at every raise site — makes each
code a valid terminal reason. Raising with a code that is not registered here is a validation
error at the raise site, so a typo can never reach a user as a silent generic message. Reason
codes are exported constants: no bare string literals at raise sites. Raw AWS, Athena or Python
text never reaches a notification body; it stays in CloudWatch and the execution history.

Every code is registered here rather than in the spec that introduced its verb, and that is
load-bearing. A terminal error validates its reason at construction against a process-global set
that each domain package extends at import. A deployed function imports only its own domain, but
the test suite imports every one into a single process — and the image now puts them all on
``/opt/python``, so nothing but the import list keeps them apart — where a sibling domain happens
to register several of the same names. Deferring registration
would therefore have shipped codes that pass CI and raise in production, and the failure state
would record that raw validation text as the user-facing reason — the exact leak the messaging
rule forbids. The tests assert against the table below, never against the global registry, for
the same reason.

Note what is deliberately absent: there is no reason code for a failed ragged or duplicates
query. Those degrade the report to not-computed and the request still succeeds, so they never
become a terminal at all. Only the profile query's failure is terminal.

Attributes:
  UNAUTHORIZED: A shared base code, re-exported so verb code has one import for every reason it
    raises. Base codes must not be re-declared in the domain table — the resolver hard-errors on
    a domain re-defining one.
  FORBIDDEN: A shared base code, re-exported for the same reason.
  UNEXPECTED_ERROR: The generic catch-all the failure decorator emits for an unexpected
    exception. Also a shared base code, re-exported for the same reason.
  INVALID_REQUEST: A malformed envelope — a missing, renamed or wrong-typed field, or no request
    id.
  LOCATION_IS_SPACE_ROOT: validate-authorize terminal. A check builds an external table over its
    target, and Athena reads a table's location RECURSIVELY, so a check at the top of a space
    reads the space's own bookkeeping — the Athena results folder (including this very check's
    output), archive receipts, shared-table copies — as if it were the user's data. It does not
    fail; it succeeds and reports the wrong numbers, which is why this is a refusal rather than a
    caveat on the report. A single file that happens to sit at the root is NOT this case: its
    queries carry a path predicate, so its numbers are its own.
  NO_DATA_FILES: inspect-source terminal.
  UNSUPPORTED_FORMAT: inspect-source terminal.
  MIXED_FORMATS: inspect-source terminal.
  TOO_MANY_FILES: inspect-source terminal.
  COMPRESSED_SOURCE_TOO_LARGE: inspect-source terminal.
  UNREADABLE_HEADER: inspect-source terminal.
  TOO_MANY_PARTITION_VALUES: inspect-source terminal.
  PARTITION_LAYOUT_MISMATCH: inspect-source terminal.
  TOO_MANY_COLUMNS: Temp-table and profile-query terminal.
  INVALID_COLUMN_NAMES: Temp-table terminal. This check cannot report on data it cannot
    read, and it cannot read data whose column names Athena will not accept — so the answer
    to "is this folder healthy?" is this refusal, naming the columns, rather than a report
    that never gets built.
  INVALID_PARTITION_NAMES: Temp-table terminal, and a SEPARATE reason from the one above
    rather than a reuse of it. The two refusals name different things and ask for different
    repairs: a bad column name is fixed by editing a file's header, a bad partition name by
    renaming an S3 folder. Told to fix a column, a user would go looking in the wrong place.
  PARTITION_COLUMN_NOT_LAST: Temp-table terminal, and a third distinct repair: the names are
    fine, their ORDER is not. A column naming a partition key is left out of the table, and a
    CSV is read by position, so one before a column the table keeps would report every later
    column against the wrong field. The build refuses the same folder under the same reason code,
    in its own words: this one says partition FOLDER, because that is where these keys come from.
  QUERY_FAILED: Profile-query terminal.
  QUERY_TIMEOUT: Profile-query terminal.
  REQUEST_ID_REUSED: inspect-source terminal. The request id is already claimed by another
    execution, so every name this run would derive from it — its temp tables, its report folder,
    its Athena tokens — already belongs to that one. Refused before anything is listed or written.
  SILENT_REASONS: Reasons that end a run without telling anyone. Registered as valid terminal
    reasons but given no wording, and both failure emitters skip them through
    ``notify.is_silent``. A reused request id is the only member. The run it collided with is the
    one that reports, and the browser mints a fresh id per submit, so a reuse comes from a request
    somebody built by hand, which has nothing it should be told.
  _BODIES: Reason code to the clause following the "Couldn't check data quality" prefix. Caps
    are baked in from the config at import, so a message quoting a limit cannot drift from the
    constant that enforces it. The remaining markers carry per-request context only a raise site
    knows. Substitution is a plain replace on named markers, never string formatting, so a
    literal brace in an S3 key cannot raise.
  resolver: The domain-scoped resolver over the shared base table, carrying this plane's
    prefix and access-denied clause as well as its bodies.
"""

from cpcommon import messages as _cpmessages

from . import config

UNAUTHORIZED = _cpmessages.UNAUTHORIZED
FORBIDDEN = _cpmessages.FORBIDDEN
UNEXPECTED_ERROR = _cpmessages.UNEXPECTED_ERROR

INVALID_REQUEST = "invalid_request"

LOCATION_IS_SPACE_ROOT = "location_is_space_root"
NO_DATA_FILES = "no_data_files"
UNSUPPORTED_FORMAT = "unsupported_format"
MIXED_FORMATS = "mixed_formats"
TOO_MANY_FILES = "too_many_files"
COMPRESSED_SOURCE_TOO_LARGE = "compressed_source_too_large"
UNREADABLE_HEADER = "unreadable_header"
TOO_MANY_PARTITION_VALUES = "too_many_partition_values"
PARTITION_LAYOUT_MISMATCH = "partition_layout_mismatch"

TOO_MANY_COLUMNS = "too_many_columns"
INVALID_COLUMN_NAMES = "invalid_column_names"
INVALID_PARTITION_NAMES = "invalid_partition_names"
PARTITION_COLUMN_NOT_LAST = "partition_column_not_last"
QUERY_FAILED = "query_failed"
QUERY_TIMEOUT = "query_timeout"
REQUEST_ID_REUSED = "request_id_reused"

SILENT_REASONS = frozenset({REQUEST_ID_REUSED})

_BODIES = {
    INVALID_REQUEST: "the request was malformed. Please try again.",
    LOCATION_IS_SPACE_ROOT: (
        "a check reads every file in the folder it's given, so it can't be run on the top of a "
        "space - that also holds your query results, archived copies and shared tables, and "
        "they'd be counted as your data. Open the folder holding the files you want checked and "
        "run it there."
    ),
    NO_DATA_FILES: "no supported data files were found there.",
    UNSUPPORTED_FORMAT: "that file format isn't supported. Please use CSV, JSON, or Parquet.",
    MIXED_FORMATS: "that folder mixes file formats ({formats}). Please check a folder that uses a single format.",
    TOO_MANY_FILES: (
        f"that folder has more than the {config.DQ_MAX_OBJECTS} files this check supports "
        "({count} found). Please check a smaller folder."
    ),
    COMPRESSED_SOURCE_TOO_LARGE: (
        "{object} is a compressed file larger than "
        f"{config.DQ_MAX_GZIP_OBJECT_BYTES // 1024**3} GB. A .gz file can't be split across "
        "workers, so checking it would run until it timed out. Please decompress it, or split "
        "it into several smaller files."
    ),
    UNREADABLE_HEADER: "the columns of {object} couldn't be read.",
    TOO_MANY_PARTITION_VALUES: (
        "the folder value {key} has more than the "
        f"{config.DQ_MAX_PARTITION_VALUES} values this check supports "
        "({count} found). Please check one of its sub-folders."
    ),
    PARTITION_LAYOUT_MISMATCH: (
        "that folder mixes partitioned and unpartitioned files (for example {object}). "
        "Every file must sit under the same key=value folders."
    ),
    TOO_MANY_COLUMNS: (
        f"that data has more than the {config.DQ_MAX_COLUMNS} columns this check supports "
        "({count} found). Please check a narrower set of files."
    ),
    INVALID_COLUMN_NAMES: (
        "these column names in that data won't work in Athena: {columns}. Athena column names "
        "can only use letters, digits and underscores, and two names that differ only by case "
        "become one column - a table built from this data would be unreadable, so the check "
        "stopped here."
    ),
    INVALID_PARTITION_NAMES: (
        "these folder names in that data won't work as partitions in Athena: {columns}. A "
        "key=value folder's key can only use letters, digits and underscores - rename the "
        "folders and check again."
    ),
    PARTITION_COLUMN_NOT_LAST: (
        "these columns have a partition folder's name and aren't at the end of the file: "
        "{columns}. A CSV file's columns are read in order, so a column named after a "
        "partition can only be left out when nothing follows it - move it to the end of your "
        "files, or take it out, and check again."
    ),
    QUERY_FAILED: "the check couldn't be completed. Please contact the Administrator.",
    QUERY_TIMEOUT: (
        "that source is too large to finish checking in the time available. "
        "Please check a smaller folder."
    ),
}

resolver = _cpmessages.register(
    _BODIES,
    prefix="Couldn't check data quality{where}: ",
    access_denied="You don't have access to check data quality there.",
)
_cpmessages.register_reasons(SILENT_REASONS)


def failure_message(reason: str, location: str = "", **tokens: str) -> str:
    """Maps a terminal reason and its context to the message the actor sees.

    The compressed-source wording does not say the file is too big, because the same data
    uncompressed passes — that would be untrue and would send the user to do the wrong thing.
    The query-failure wording carries no raw Athena text: that stays in CloudWatch and the
    execution history where an operator can read it, and Athena's failure text routinely names
    internal serde classes and byte offsets, which tells a user nothing and leaks
    implementation. The timeout wording deliberately avoids the word timeout, which reads as a
    transient hiccup worth retrying — the query timeout is an account-level quota, so the
    identical request will time out again, and the message names the thing that actually changes
    the outcome.

    Args:
      reason: The terminal reason code. An unknown one falls back to the shared generic rather
        than leaking the code.
      location: The checked location, named in the sentence when known.
      **tokens: Per-request marker values only a raise site knows. Caps are already baked in at
        import. A marker left unfilled survives into the body verbatim, so the emitter must pass
        the tokens for whichever reason it is rendering; the tests pin which reasons take which.

    Returns:
      The full actor-facing sentence.

    Raises:
      None.
    """
    return resolver.message(
        reason, **{**tokens, "where": f' on "{location}"' if location else ""}
    )


def success_message(location: str) -> str:
    """Composes the message the actor sees when a check completes.

    It names the location and says it finished, and nothing else. The message used to carry the
    verdict, the first findings, the total count and two caveat clauses; that is the report's
    job, and the notification links straight to it. An inbox line that restates the findings is
    both read and ignored in the same glance, and it forced every reader to reconcile a one-line
    summary against the page it links to. Narrowing it also retires the unqualified-clean problem
    outright: this wording makes no claim about the data at all, so there is nothing to qualify.

    The caller adds the report link separately; this returns text only, and that text becomes the
    link's accessible name — which is why it names the location rather than saying "your check
    finished".

    Args:
      location: The checked location, named in the sentence when known.

    Returns:
      The full actor-facing sentence.

    Raises:
      None.
    """
    where = f' on "{location}"' if location else ""
    return f"Data quality check{where} finished — open the report for details."
