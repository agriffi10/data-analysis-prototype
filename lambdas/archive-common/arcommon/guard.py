"""The destination guard: nothing a restore would write over may already exist.

SPEC-170 FR-004, and the rule the feature was asked for explicitly. S3 has no move and no
rename, so a restore is a copy and a copy overwrites. If the user has re-created
``reports/q1.csv`` since archiving it, restoring on top would destroy the newer file with no
trace — so **any** occupied destination refuses the whole restore. There is no skip, no
overwrite, no merge and no "restore what fits".

**The guard runs before any ``RestoreObject``, and that ordering is the reason SPEC-170 exists
as its own spec.** Glacier retrieval is billed and irreversible once initiated: discovering the
conflict afterwards would charge the user for hours of retrieval that cannot land, and there is
no way to give it back.

**A ``403`` counts as OCCUPIED.** A key this role cannot head is a key it must not overwrite —
and on these buckets that is a live case rather than a hypothetical, because the execution
role's own policy Denies it under ``athenaresults/``, ``user_settings/`` and ``archive/``.
Reading an ambiguous answer as "clear" is the one mistake here that ends in data loss, which is
the same fail-closed direction file-send's guard takes when its listing faults.

Attributes:
  _ABSENT_STATUSES: The HTTP statuses that mean the key is not there. ``404`` is the ordinary
    answer for a missing object; ``403`` is deliberately NOT here and is documented above.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from cpcommon import clients, errors
from cpcommon.errors import TerminalError

from . import messages  # noqa: F401
from .config import RESTORE_CONFLICT_SAMPLE, RESTORE_HEAD_CONCURRENCY

logger = logging.getLogger()

_ABSENT_STATUSES = (404,)


def _status(err) -> int:
    """Reads an S3 error's HTTP status, or 0 when it carries none.

    Args:
      err: The exception a ``head_object`` call raised.

    Returns:
      The HTTP status code, or 0.

    Raises:
      None.
    """
    meta = getattr(err, "response", None) or {}
    return int((meta.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0)


def _is_occupied(bucket: str, key: str) -> bool:
    """Reports whether one destination key is already taken.

    A folder placeholder is an object like any other and counts as a collision — restoring over
    one would be harmless in itself, but a rule with an exception is a rule someone extends, and
    the whole value of this guard is that it has none.

    Args:
      bucket: The space bucket the restore would write into.
      key: The destination key.

    Returns:
      True when the key exists or cannot be read.

    Raises:
      TransientError: On a throttle or 5xx. A guard that cannot see the destination must retry
        and then fail its own state — never fall through to "nothing is there", which is the one
        answer that ends in an overwrite.
    """
    try:
        clients.s3().head_object(Bucket=bucket, Key=key)
    except Exception as err:  # noqa: BLE001 - anything but a proven 404 is treated as occupied
        errors.raise_if_transient(err, f"head {bucket}/{key}")
        if _status(err) in _ABSENT_STATUSES:
            return False
        logger.info("treating %s/%s as occupied: %s", bucket, key, err)
        return True
    return True


def find_collisions(bucket: str, dest_keys: list, space_root: str) -> list:
    """Returns a bounded sample of destinations that are already occupied.

    **It short-circuits on the ROUND that finds the first collision, not on a full sample**, and
    the difference is the whole point of the requirement: one re-created file is the likeliest
    real conflict there is, and waiting for ``RESTORE_CONFLICT_SAMPLE`` of them means heading every
    destination in the archive to report a conflict found in the first eight. **Measured on this
    code before the fix: 20,000 heads to report a single collision at index 3.**

    Stopping at the round rather than at the key keeps the pool's own work coherent — the round is
    already in flight — and it is why the sample is a sample: the guard genuinely does not know how
    many more there are, and the message says so.

    Order is the PLAN's, which is the archive's own listing order, so the paths a user is shown
    are the ones nearest the top of the folder they are looking at.

    Args:
      bucket: The space bucket the restore would write into.
      dest_keys: Every destination key, in plan order.
      space_root: The space root the sample is rendered relative to — the user reads a path they
        recognise from the file browser, never an ``s3://`` URI.

    Returns:
      Up to ``RESTORE_CONFLICT_SAMPLE`` occupied keys, relative to the space root.

    Raises:
      TransientError: On a throttle or 5xx from any head.
    """
    concurrency = RESTORE_HEAD_CONCURRENCY
    def check(key: str) -> bool:
        """Heads one destination key in the bucket this call is guarding.

        Args:
          key: The destination key.

        Returns:
          True when the key is occupied.

        Raises:
          TransientError: On a throttle or 5xx.
        """
        return _is_occupied(bucket, key)

    found: list = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for start in range(0, len(dest_keys), concurrency):
            batch = dest_keys[start : start + concurrency]
            for key, occupied in zip(batch, pool.map(check, batch), strict=True):
                if occupied:
                    found.append(key.removeprefix(space_root))
            if found:
                return found[:RESTORE_CONFLICT_SAMPLE]
    return found


def assert_clear(bucket: str, dest_keys: list, space_root: str) -> None:
    """Refuses the whole restore if any destination is occupied.

    Args:
      bucket: The space bucket the restore would write into.
      dest_keys: Every destination key, in plan order.
      space_root: The space root the sample is rendered relative to.

    Returns:
      None.

    Raises:
      TerminalError: ``destination_occupied``, carrying the sample as a user-facing token — the
        user's own paths, never service text.
      TransientError: On a throttle or 5xx from any head.
    """
    collisions = find_collisions(bucket, dest_keys, space_root)
    if not collisions:
        return
    raise TerminalError(
        "destination_occupied",
        f"{len(collisions)} or more destination(s) under {space_root} are already occupied",
        tokens={"sample": ", ".join(collisions)},
    )
