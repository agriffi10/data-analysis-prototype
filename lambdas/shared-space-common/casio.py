"""Optimistic compare-and-swap over conditional S3 writes.

Both the registry, the source of truth, and the per-user cache write JSON control objects that
concurrent executions can touch at once — the Pipe starts the state machine fire-and-forget, so
serial intake is not serial execution, and a plain read-then-write would lose updates. This
module owns the one CAS discipline both use, so their precondition and retry semantics cannot
drift: read with the entity tag, apply to the freshly-read value, write conditioned on that tag
or on absence, and on a precondition failure re-read, re-apply and retry.

Callers supply the read and write closures, because each module keeps its own key layout,
serialization and absent-detection — the registry treats only a missing key as absent, while
the cache also treats a denial from a missing list permission as absent. Only the loop and the
precondition detection are shared here.

Attributes:
  MAX_CAS_ATTEMPTS: Attempts before giving up. Contention is rare — a few concurrent operations
    on one space or user — so a small cap is plenty, and exhausting it raises rather than
    silently dropping a write.
"""

import logging

from cpcommon.errors import error_code

logger = logging.getLogger()

MAX_CAS_ATTEMPTS = 6


__all__ = ["MAX_CAS_ATTEMPTS", "cas_mutate", "error_code", "is_precondition"]


def is_precondition(exc):
    """Reports whether a conditional write lost to a concurrent writer.

    Both codes matter, and the second was once missing. S3 answers a failed match-on-tag with
    one code, but a failed create-only write raced against another create with a different one —
    a genuinely simultaneous write, where the first code is the sequential case. This module's
    two twins already handle it, and one notes that treating the conflict as a hard error would
    drop the first run. Three create-only writes depended on this, so a genuinely concurrent
    create failed hard instead of re-reading and resolving.

    Args:
      exc: The write fault.

    Returns:
      True when the fault is a precondition failure.

    Raises:
      None.
    """
    return error_code(exc) in ("PreconditionFailed", "412", "ConditionalRequestConflict", "409")


def cas_mutate(read, apply, write, *, label="object", max_attempts=MAX_CAS_ATTEMPTS):
    """Compare-and-swaps an object through a transform, retrying on a concurrent writer.

    The write is caught broadly so a fake or a real client error is handled the same way, and
    only a genuine precondition failure retries — anything else re-raises. The read runs outside
    that guard, so an unexpected read error propagates rather than causing a silent overwrite.

    Args:
      read: Returns the current ``(value, etag)``. A None tag marks create-if-absent on the
        write back.
      apply: Returns the new value. Returning a value equal to the input skips the write as a
        true no-op.
      write: Performs the conditional write, raising the client's error on a precondition
        failure.
      label: Name used in the exhaustion message.
      max_attempts: Attempts before giving up.

    Returns:
      The committed value, or the unchanged one when the transform was a no-op.

    Raises:
      RuntimeError: When the attempts are exhausted.
      ClientError: Any write fault that is not a precondition failure, and any read fault.
    """
    for _ in range(max_attempts):
        value, etag = read()
        updated = apply(value)
        if updated == value:
            return updated
        try:
            write(updated, etag)
            return updated
        except Exception as exc:
            if not is_precondition(exc):
                raise
    raise RuntimeError(f"CAS for {label} exhausted {max_attempts} attempts")
