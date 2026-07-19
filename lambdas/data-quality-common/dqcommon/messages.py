"""User-facing data-quality notification text + reason codes (SPEC-109 seeds; SPEC-114 fills).

Registers this domain's reason codes with ``cpcommon.messages`` (SPEC-107 FR-005): that
gives a DOMAIN-SCOPED resolver over the shared base table, and — the part that matters at
every raise site — makes each code a VALID ``TerminalError`` reason. Raising a
``TerminalError`` with a code that isn't registered here is a ``ValueError`` AT THE RAISE
SITE, so a typo can never reach a user as a silent generic message.

Reason codes are EXPORTED CONSTANTS: no bare string literals at raise sites.

Raw AWS/Athena/Python text never reaches a notification body (SPEC-106) — it stays in
CloudWatch and the SFN execution history. SPEC-114 adds the verdict/top-issues wording and
the emitters; this module carries only what SPEC-109's validate-authorize raises.
"""

from cpcommon import messages as _cpmessages

from . import config

# ── Exported reason-code constants ───────────────────────────────────────────
# `unauthorized` / `forbidden` are cpcommon BASE codes, re-exported so verb code has ONE
# import for every reason it raises. They must NOT be re-declared in _BODIES below — the
# resolver hard-errors on a domain re-defining a shared base code.
UNAUTHORIZED = _cpmessages.UNAUTHORIZED
FORBIDDEN = _cpmessages.FORBIDDEN

#: A malformed envelope: missing/renamed/wrong-typed field, or no requestId (SPEC-109 FR-001).
INVALID_REQUEST = "invalid_request"

# ── inspect-source terminals (SPEC-110 FR-007) ───────────────────────────────
# These are registered HERE, not in SPEC-114, and that is load-bearing rather than
# tidiness. TerminalError validates its reason AT CONSTRUCTION against a PROCESS-GLOBAL
# set (cpcommon/errors.py) that each domain layer extends AT IMPORT. The deployed
# data-quality functions attach cpcommon + dqcommon (+ polars) and never import
# tbcommon — but `pytest lambdas/` imports every domain layer into ONE process, where
# tbcommon happens to register no_data_files / unsupported_format / mixed_formats
# (tbcommon/messages.py). Deferring registration would therefore have shipped three
# codes that pass CI and raise ValueError in production, and RecordFailure would record
# that raw ValueError text as the user-facing reason (the exact leak SPEC-106 FR-008
# forbids). test_messages.py asserts against _BODIES, never is_known_reason, for the
# same reason. This is the PR #196 shape: a test process satisfying an import-time
# contract that a deployed function does not.
NO_DATA_FILES = "no_data_files"
UNSUPPORTED_FORMAT = "unsupported_format"
MIXED_FORMATS = "mixed_formats"
TOO_MANY_FILES = "too_many_files"
COMPRESSED_SOURCE_TOO_LARGE = "compressed_source_too_large"
UNREADABLE_HEADER = "unreadable_header"
TOO_MANY_PARTITION_VALUES = "too_many_partition_values"
PARTITION_LAYOUT_MISMATCH = "partition_layout_mismatch"

# ── temp-table + profile-query terminals (SPEC-111 FR-001/FR-004) ────────────
# Registered here for the same reason as the block above: TerminalError validates its
# reason at CONSTRUCTION against a process-global set, so a code that isn't in _BODIES
# raises ValueError at the raise site — in production, on the deployed function, where
# `pytest lambdas/` would not have caught it.
#
# NOTE what is NOT here: there is no reason code for a failed RAGGED or DUPLICATES query.
# That is the point of FR-003 — those two degrade the report to `not_computed` and the
# request still SUCCEEDS, so they never become a terminal at all. Only the PROFILE
# query's failure is terminal.
TOO_MANY_COLUMNS = "too_many_columns"
QUERY_FAILED = "query_failed"
QUERY_TIMEOUT = "query_timeout"

# reason -> the clause after 'Couldn't check data quality[ on "{location}"]: '.
#
# Caps are baked in from dqcommon.config at import (an f-string), so a message that
# quotes a limit cannot drift from the constant that enforces it. The remaining
# {token} markers carry per-request context (the offending object, an observed count)
# that only the raise site knows; SPEC-114's emitter fills them via failure_message(...).
# Substitution is str.replace on named markers, never str.format, so a literal brace in
# an S3 key can't raise (SPEC-083 FR-005 / SPEC-106).
_BODIES = {
    INVALID_REQUEST: "the request was malformed. Please try again.",
    NO_DATA_FILES: "no supported data files were found there.",
    UNSUPPORTED_FORMAT: "that file format isn't supported. Please use CSV, JSON, or Parquet.",
    MIXED_FORMATS: "that folder mixes file formats ({formats}). Please check a folder that uses a single format.",
    TOO_MANY_FILES: (
        f"that folder has more than the {config.DQ_MAX_OBJECTS} files this check supports "
        "({count} found). Please check a smaller folder."
    ),
    # NOT "the file is too big": the same data uncompressed passes, so that would be untrue
    # and would send the user to do the wrong thing (SPEC-110 FR-004 / SPEC-114 FR-002).
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
    # NO RAW ATHENA TEXT (SPEC-106 FR-008). The StateChangeReason stays in CloudWatch and
    # the Step Function execution history, where an operator can read it; the user gets a
    # sentence they can act on. Athena's failure text routinely names internal serde
    # classes and byte offsets, which tells a user nothing and leaks implementation.
    QUERY_FAILED: "the check couldn't be completed. Please contact the Administrator.",
    # DELIBERATELY not "the check timed out" — that reads as a transient hiccup worth
    # retrying, and this is not: the DML query timeout is an ACCOUNT-LEVEL Service Quota
    # (30 minutes by default), so the identical request will time out again. Tell the user
    # the thing that actually changes the outcome.
    QUERY_TIMEOUT: (
        "that source is too large to finish checking in the time available. "
        "Please check a smaller folder."
    ),
}

#: Domain-scoped resolver (shared base table + the domain table above), SPEC-107 FR-005.
resolver = _cpmessages.register(_BODIES)


def failure_message(reason: str, location: str = "", **tokens: str) -> str:
    """Map a terminal reason (+ context) to the message the actor sees.

    An unknown reason falls back to the shared generic rather than leaking the code, and no
    raw AWS/Athena text is ever interpolated (SPEC-106 FR-008). SPEC-114 extends this with
    the verdict/top-issues wording.

    ``tokens`` fill the per-request {object}/{count}/{key}/{formats} markers in _BODIES —
    the context only a raise site knows (caps are already baked in at import). A marker
    left unfilled survives into the body verbatim, so SPEC-114's emitter must pass the
    tokens for whichever reason it is rendering; test_messages.py pins which reasons take
    which.
    """
    if reason in (UNAUTHORIZED, FORBIDDEN):
        return "You don't have access to check data quality there."
    where = f' on "{location}"' if location else ""
    return f"Couldn't check data quality{where}: {resolver.body(reason, **tokens)}"
