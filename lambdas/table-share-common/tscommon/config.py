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
  SHARE_MAX_DEFINITION_BYTES: Cap on the serialised cloned table definition — the last
    unbounded term on the Map's state, and a user-controlled one, since a user can set both
    columns and table properties from the query workspace. Rejected in inspect-source as a
    whole-request terminal before any recipient runs.
"""

SHARE_MAX_OBJECTS = 1000
SHARE_MAX_TOTAL_BYTES = 20 * 1024**3

RECIPIENT_KINDS = frozenset({"user", "space"})

SHARE_MAX_RECIPIENTS = 50

SHARE_MAX_DEFINITION_BYTES = 32 * 1024
