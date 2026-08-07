"""User-facing data-quality notification text and reason codes.

Registers this domain's reason codes with the shared registry, which gives a domain-scoped
resolver over the shared base table and — the part that matters at every raise site — makes each
code a valid terminal reason. Raising with a code that is not registered here is a validation
error at the raise site, so a typo can never reach a user as a silent generic message. Reason
codes are exported constants: no bare string literals at raise sites. Raw AWS, Athena or Python
text never reaches a notification body; it stays in CloudWatch and the execution history.

Every code is registered here rather than in the spec that introduced its verb, and that is
load-bearing. A terminal error validates its reason at construction against a process-global set
that each domain layer extends at import. The deployed functions attach only their own layers
and never import another domain's, but the test suite imports every layer into one process,
where a sibling domain happens to register several of the same names. Deferring registration
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
  NO_DATA_FILES: inspect-source terminal.
  UNSUPPORTED_FORMAT: inspect-source terminal.
  MIXED_FORMATS: inspect-source terminal.
  TOO_MANY_FILES: inspect-source terminal.
  COMPRESSED_SOURCE_TOO_LARGE: inspect-source terminal.
  UNREADABLE_HEADER: inspect-source terminal.
  TOO_MANY_PARTITION_VALUES: inspect-source terminal.
  PARTITION_LAYOUT_MISMATCH: inspect-source terminal.
  TOO_MANY_COLUMNS: Temp-table and profile-query terminal.
  QUERY_FAILED: Profile-query terminal.
  QUERY_TIMEOUT: Profile-query terminal.
  _BODIES: Reason code to the clause following the "Couldn't check data quality" prefix. Caps
    are baked in from the config at import, so a message quoting a limit cannot drift from the
    constant that enforces it. The remaining markers carry per-request context only a raise site
    knows. Substitution is a plain replace on named markers, never string formatting, so a
    literal brace in an S3 key cannot raise.
  resolver: The domain-scoped resolver over the shared base table.
"""

from cpcommon import messages as _cpmessages

from . import config

UNAUTHORIZED = _cpmessages.UNAUTHORIZED
FORBIDDEN = _cpmessages.FORBIDDEN
UNEXPECTED_ERROR = _cpmessages.UNEXPECTED_ERROR

INVALID_REQUEST = "invalid_request"

NO_DATA_FILES = "no_data_files"
UNSUPPORTED_FORMAT = "unsupported_format"
MIXED_FORMATS = "mixed_formats"
TOO_MANY_FILES = "too_many_files"
COMPRESSED_SOURCE_TOO_LARGE = "compressed_source_too_large"
UNREADABLE_HEADER = "unreadable_header"
TOO_MANY_PARTITION_VALUES = "too_many_partition_values"
PARTITION_LAYOUT_MISMATCH = "partition_layout_mismatch"

TOO_MANY_COLUMNS = "too_many_columns"
QUERY_FAILED = "query_failed"
QUERY_TIMEOUT = "query_timeout"

_BODIES = {
    INVALID_REQUEST: "the request was malformed. Please try again.",
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
    QUERY_FAILED: "the check couldn't be completed. Please contact the Administrator.",
    QUERY_TIMEOUT: (
        "that source is too large to finish checking in the time available. "
        "Please check a smaller folder."
    ),
}

resolver = _cpmessages.register(_BODIES)


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
    if reason in (UNAUTHORIZED, FORBIDDEN):
        return "You don't have access to check data quality there."
    where = f' on "{location}"' if location else ""
    return f"Couldn't check data quality{where}: {resolver.body(reason, **tokens)}"


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
