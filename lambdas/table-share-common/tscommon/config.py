"""Domain configuration for the table-share control plane.

The shared core — region, user pool identifiers, buckets, workgroup, notifications queue, the
catalog identifier rule — lives in ``cpcommon.config``. Only table-share's own constants live
here. The sizing evidence behind the three caps is in ``docs/lambda-rationale.md``.

Attributes:
  SHARE_MAX_OBJECTS: Object-count cap. A share exceeding it is a whole-request terminal
    failure — too large for this version, with S3 Batch Operations the deferred escape hatch.
    Sized so a recipient's parallel server-side copy finishes comfortably inside the copy
    verb's timeout.
  SHARE_MAX_TOTAL_BYTES: Total-size cap, sized the same way.
  RECIPIENT_KINDS: The two recipient kinds a share request may target.
  SHARE_MAX_RECIPIENTS: Recipient cap. What it prevents is not the fan-out but the Map's
    result: each failed item carries the raw Step Functions error, and breaching the 256 KB
    state payload raises a limit error on the Map that destroys every per-recipient outcome
    the Map exists to preserve. A test computes the worst case from these constants, so
    changing one without re-checking the other fails the build.
  SHARE_MAX_DEFINITION_BYTES: Sanity check on the serialised cloned table definition, and
    since SPEC-161 that is ALL it is — it is no longer a bound on the Step Functions state,
    because the definition travels by pointer. What sizes it now is Athena's query-string
    quota: the definition is rendered into one CREATE EXTERNAL TABLE, and Athena refuses a
    query string over 262,144 bytes (a hard quota). The rendered DDL is of the same order as
    the serialised JSON — the backticks and quotes replace the JSON keys — so a 128 KiB
    ceiling on the object leaves roughly a factor of two before the statement itself is
    refused. Rejected in inspect-source as a whole-request terminal, before the write and
    before any recipient runs, so nobody gets a definition that cannot be rendered.
"""

SHARE_MAX_OBJECTS = 1000
SHARE_MAX_TOTAL_BYTES = 20 * 1024**3

RECIPIENT_KINDS = frozenset({"user", "space"})

SHARE_MAX_RECIPIENTS = 50

SHARE_MAX_DEFINITION_BYTES = 128 * 1024
