"""Optimistic compare-and-swap over conditional S3 ``PutObject``.

Both the registry (source of truth) and the per-user cache write JSON control objects
that concurrent control-plane executions can touch at once (the Pipe starts the
Standard state machine fire-and-forget, so serial intake is not serial execution). A
plain read-then-write would lose updates. This module owns the one CAS discipline both
use, so their precondition/retry semantics can't drift (SPEC-082 FR-003):

    read (+ETag) → apply to the freshly-read value → ``PutObject`` conditioned on that
    ETag (``If-Match``) or on absence (``If-None-Match: *``); a 412 means a concurrent
    writer committed first, so re-read, re-apply, and retry up to ``MAX_CAS_ATTEMPTS``.

Callers supply the ``read``/``write`` closures (each module keeps its own key layout,
serialization, and absent-detection — the registry treats only ``NoSuchKey`` as absent,
while the cache also treats a ``403`` from a missing ``s3:ListBucket`` as absent). Only
the loop and precondition detection are shared here.
"""

import logging

logger = logging.getLogger()

# Contention is rare (a few concurrent ops on one space/user), so a small cap is
# plenty; exhausting it raises rather than silently dropping a write.
MAX_CAS_ATTEMPTS = 6


def error_code(exc):
    """The S3 error code from a botocore/fake ClientError, or "" if it has none."""
    return str((getattr(exc, "response", {}) or {}).get("Error", {}).get("Code", ""))


def is_precondition(exc):
    """True when a conditional PutObject failed (412), i.e. a concurrent writer won."""
    return error_code(exc) in ("PreconditionFailed", "412")


def cas_mutate(read, apply, write, *, label="object", max_attempts=MAX_CAS_ATTEMPTS):
    """Compare-and-swap an object through ``apply``, retrying on a concurrent-writer 412.

    ``read()`` returns ``(value, etag)`` for the current object (``etag`` None marks
    create-if-absent on the write back). ``apply(value)`` returns the new value; return
    a value equal to the input to skip the write as a true no-op. ``write(new_value,
    etag)`` performs the conditional PutObject and raises the client's ``ClientError``
    on a precondition failure. Returns the committed (or unchanged) value.

    The write is caught broadly so a fake or real ``ClientError`` is handled the same
    way; only a genuine precondition failure retries — anything else re-raises. ``read``
    runs outside the guard, so an unexpected read error propagates (never a silent
    overwrite).
    """
    for _ in range(max_attempts):
        value, etag = read()
        updated = apply(value)
        if updated == value:
            return updated  # nothing changed — don't write
        try:
            write(updated, etag)
            return updated
        except Exception as exc:  # noqa: BLE001 — re-raised unless it's a precondition
            if not is_precondition(exc):
                raise  # a real write error — propagate, never a silent overwrite
            # a concurrent writer won; loop to re-read and re-apply (or exhaust below)
    raise RuntimeError(f"CAS for {label} exhausted {max_attempts} attempts")
