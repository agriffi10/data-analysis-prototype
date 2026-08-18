"""Optimistic compare-and-swap over conditional S3 writes — the fleet's one loop.

Every JSON control object this fleet writes can be touched by two executions at once: the
shared-space registry and per-user caches (the Pipe starts state machines fire-and-forget, so
serial intake is not serial execution), the per-space data-quality runs index (checks of
different locations run in parallel), and the structured-log day objects (two sweeps can land
on one day). A plain read-then-write loses updates in all four cases. The discipline is the
same one each time: read with the entity tag, apply to the freshly-read value, write
conditioned on that tag or on absence, and on a precondition failure re-read, re-apply, retry.

**It was written three times.** ``dqcommon/index_store.py`` called its copy "a deliberate twin,
not drift" and named SPEC-125 as the point where they would converge; SPEC-125 shipped and they
drifted anyway — two copies handled the racing 409 and one did not, and the caps were 6, 5 and
5. This is that convergence, one spec late.

Callers supply the read and write closures, because each owns its key layout, serialization
and absent-detection — the registry treats only a missing key as absent, the cache also treats
a missing list permission as absent, and the log sweep treats ANY read failure as absent so a
transient error can never silently overwrite a day. Only the loop and the precondition
detection are shared.

Attributes:
  MAX_ATTEMPTS: Attempts before giving up, for every caller. Contention is rare everywhere it
    is used — a few concurrent operations on one space, user, or day — so a small cap is
    plenty, and exhausting it is surfaced rather than silently dropping a write. Six, which was
    the shared-space value; the data-quality copy's own docstring said it "mirrors the
    shared-space primitive rather than inventing a number" while being five, so raising it to
    six executes the intent that was already written down. A higher cap costs one more re-read
    only under genuine contention, and the two callers that swallow exhaustion lose a row or
    leave events queued when they hit it — both worth one more try.
"""

import logging
from collections.abc import Callable
from typing import Any

from .errors import error_code

logger = logging.getLogger()

MAX_ATTEMPTS = 6

__all__ = ["MAX_ATTEMPTS", "CasExhausted", "cas_mutate", "is_precondition"]


class CasExhausted(RuntimeError):
    """Every attempt lost to a concurrent writer.

    A ``RuntimeError`` subclass rather than a new hierarchy: callers that predate this module
    catch ``RuntimeError`` and must keep working. The distinct type exists for the caller that
    reports exhaustion differently from a write fault — ``log-sweep`` emits a different failure
    reason for each, and telling them apart by message text is how that stops being true.
    """


def is_precondition(exc):
    """Reports whether a conditional write lost to a concurrent writer.

    Both codes matter, and the second was once missing in one of the three copies. S3 answers a
    failed match-on-tag with one code, but a failed create-only write raced against another
    create with a different one — a genuinely simultaneous write, where the first code is the
    sequential case. Treating that conflict as a hard error drops the first run a space ever
    records: exactly the case where the object does not exist yet and two writers are most
    likely to create it at once.

    Args:
      exc: The write fault.

    Returns:
      True when the fault is a precondition failure.

    Raises:
      None.
    """
    return error_code(exc) in ("PreconditionFailed", "412", "ConditionalRequestConflict", "409")


def cas_mutate[T](
    read: Callable[[], tuple[Any, Any]],
    apply: Callable[[Any], T],
    write: Callable[[T, Any], Any],
    *,
    label: str = "object",
    max_attempts: int = MAX_ATTEMPTS,
    on_conflict: Callable[[int], Any] | None = None,
    skip_no_op: bool = True,
) -> T:
    """Compare-and-swaps an object through a transform, retrying on a concurrent writer.

    The write is caught broadly so a fake or a real client error is handled the same way, and
    only a genuine precondition failure retries — anything else re-raises. The read runs outside
    that guard, so an unexpected read error propagates rather than causing a silent overwrite.

    Args:
      read: Returns the current ``(value, etag)``. A None tag marks create-if-absent on the
        write back.
      apply: Returns the new value, applied to the freshly-read one on every attempt — reusing
        a value read before a losing write would re-introduce the lost update this exists to
        prevent.
      write: Performs the conditional write, raising the client's error on a precondition
        failure.
      label: Name used in the exhaustion message.
      max_attempts: Attempts before giving up.
      on_conflict: Called with the 1-based attempt number after each precondition failure, for
        a caller that narrates contention. The retry count is the signal worth recording: a
        write that succeeds on the fourth attempt is one that nearly did not.
      skip_no_op: Whether a transform returning a value equal to its input skips the write.
        True is the shared-space contract. The two callers that always produce a new value pass
        False rather than relying on inequality, so an append that happens to reproduce the
        current document still writes, exactly as their own loops did.

    Returns:
      The committed value, or the unchanged one when the transform was a skipped no-op.

    Raises:
      CasExhausted: When the attempts are exhausted.
      ClientError: Any write fault that is not a precondition failure, and any read fault.
    """
    for attempt in range(max_attempts):
        value, etag = read()
        updated = apply(value)
        if skip_no_op and updated == value:
            return updated
        try:
            write(updated, etag)
            return updated
        except Exception as exc:
            if not is_precondition(exc):
                raise
            if on_conflict is not None:
                on_conflict(attempt + 1)
    raise CasExhausted(f"CAS for {label} exhausted {max_attempts} attempts")
