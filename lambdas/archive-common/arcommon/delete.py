"""Batched object deletion with the discipline the shared-space teardown established, for the two verbs that delete.

Both callers hand it a list of keys and a prefix they are allowed to delete beneath: delete-source
removes the archived originals from the user's space, and the rollback removes a partial archive
copy from the vault. The algorithm is identical and the CONSEQUENCE of a partial failure is not,
so this module counts and reports while the verbs decide — a source deletion that half-worked is a
terminal failure, and a rollback that half-worked changes nothing about the outcome, because the
property that matters there (the source is intact) is already true.

**``DeleteObjects`` returns HTTP 200 with a per-item ``Errors`` array.** A key that was denied or
failed individually does not raise, so a response inspected only by status code reads as a
complete deletion — the defect that was fixed on the shared-space teardown, where it freed a space
name whose objects were still in the bucket. ``Quiet: False`` is set explicitly so that array is
populated at all.

**Every batch is attempted before anything is reported.** A denial on one key must not strand the
rest, and the count is only meaningful whole.

**Counts, never keys.** The numbers reach a user-facing message, the Step Functions record and
``logs/service=archive/``; a failure naming file paths is a disclosure this plane has no reason to
make, and the field rule binds what a call site chooses to emit. How many of the failures were
folder placeholders is counted apart, because the sentence delete-source raises names files and
counts a placeholder only when it is one of the things left behind.

**The source deletion is also conditional on the original being UNCHANGED, and the rollback and
the vault sweep are not.** What the vault holds is what the copy read, so an original written over
after the plan listed it is newer than its archived copy, and with versioning off deleting it
destroys the only copy of what the user last wrote. ``changed_keys`` heads each original and
compares the plan's tag, the same HEAD-compare the file-operations move runs; a conditional
``DeleteObjects`` is not used because whether S3 enforces its ETag on these buckets is unproven,
and a condition serialized and ignored would delete silently. The residual is the gap between a
head and its batch's delete, which is milliseconds against the minutes a copy takes.

Attributes:
  MAX_KEYS_PER_BATCH: S3's own limit on one ``DeleteObjects`` request.
  _ABSENT_CODES: What a head of an object that is not there answers. Absent is not a change: a
    Retry re-heads keys its first attempt already removed, and the deletion treats them the same
    way.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from cpcommon import clients, errors
from cpcommon.errors import TerminalError, TransientError
from cpcommon.paths import has_dot_segment

from . import (
    counts,
    messages,  # noqa: F401
)
from .config import PROTECTED_MARKER_BASENAME, SOURCE_HEAD_CONCURRENCY

logger = logging.getLogger(__name__)

MAX_KEYS_PER_BATCH = 1000

_ABSENT_CODES = frozenset({"NoSuchKey", "NotFound", "404"})


def assert_deletable(keys: list, allowed_prefix: str) -> None:
    """Confirms every key may be deleted, BEFORE the first batch is issued.

    Three rules, and the ordering is the point of the function. Both bucket policies deny
    ``s3:DeleteObject`` on ``*/DO_NOT_DELETE.txt`` at any depth, and the execution role is denied
    the portal's own folders — so a list carrying one of those does not fail as a whole, it fails
    PART WAY THROUGH, after some of the user's data has already been deleted. Checking the whole
    list up front turns that into a refusal that has moved nothing.

    **Containment is BOTH rules, not just the prefix one** (``cpcommon.paths``). A key is rebuilt
    here from a root and a stored relative key, and ``"alice/../bob/secrets.csv"`` starts with
    ``"alice/"`` — so a prefix test alone accepts it. S3 resolves nothing, so such a key names an
    object that almost certainly does not exist and no delete of anyone else's data follows; the
    rule is here because a containment rule that holds only while every consumer stays careful is
    not a rule, and this consumer is the one that deletes.

    Reaching any of the three means an upstream guarantee has already broken: validate-authorize
    refuses a selected marker, the expansion excludes markers and portal-managed folders, and the
    containment re-check runs on every listed key. That is what makes this defence in depth
    rather than the first line of it — and why it fails loudly rather than filtering, because a
    silent filter here would delete a source the archive is missing objects from.

    Args:
      keys: The absolute keys about to be deleted.
      allowed_prefix: The only prefix these keys may sit under.

    Returns:
      None.

    Raises:
      TerminalError: ``forbidden`` for a key outside the allowed prefix or carrying a dot
        segment, or ``protected_marker`` for a prefix marker.
    """
    for key in keys:
        if not isinstance(key, str) or not key.startswith(allowed_prefix):
            raise TerminalError("forbidden", f"{key!r} is not inside {allowed_prefix!r}")
        if has_dot_segment(key):
            raise TerminalError(
                "forbidden", f"{key!r} carries a path segment that is not allowed"
            )
        if key.rsplit("/", 1)[-1] == PROTECTED_MARKER_BASENAME:
            raise TerminalError(
                "protected_marker",
                f"{key!r} is undeletable, so the deletion was not attempted",
                tokens={"itemName": PROTECTED_MARKER_BASENAME},
            )


def delete_keys(bucket: str, keys: list, allowed_prefix: str) -> dict:
    """Deletes every key in batches, reporting how many did not go.

    Replay-safe by construction: S3 reports an already-absent key as deleted, so a re-driven
    execution completes rather than failing on the work its predecessor finished. That is what
    makes the state's ``Retry`` safe on a verb whose effect is a deletion.

    A transient fault on one batch is collected rather than raised immediately, so the remaining
    batches are still attempted, and re-raised at the end — the caller's ``Retry`` then re-runs
    the whole verb, which the replay-safety above makes correct.

    Args:
      bucket: The bucket to delete from.
      keys: The absolute keys to delete.
      allowed_prefix: The only prefix these keys may sit under, checked before anything is
        issued.

    Returns:
      ``{"deleted": n, "failed": m, "failedFolders": f}`` — counts only, ``f`` being how many of
      the ``m`` were folder placeholders. A whole batch that failed counts from its own keys, and
      an ``Errors`` entry from the key S3 names in it.

    Raises:
      TerminalError: ``forbidden`` or ``protected_marker`` from the pre-check, before any delete
        is issued.
      TransientError: When a batch failed retryably, after every batch has been attempted.
    """
    assert_deletable(keys, allowed_prefix)

    s3 = clients.s3()
    failed = 0
    failed_folders = 0
    transient = None
    for start in range(0, len(keys), MAX_KEYS_PER_BATCH):
        batch = keys[start : start + MAX_KEYS_PER_BATCH]
        try:
            response = s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": False},
            )
        except Exception as exc:  # noqa: BLE001
            try:
                errors.raise_if_transient(exc, f"delete {len(batch)} object(s) in {bucket}")
            except TransientError as retryable:
                transient = transient or retryable
                continue
            logger.warning("a delete batch of %d object(s) in %s failed", len(batch), bucket)
            failed += len(batch)
            failed_folders += len(batch) - counts.count_files(batch)
            continue
        refused = response.get("Errors") or []
        failed += len(refused)
        failed_folders += sum(
            1 for error in refused if counts.is_folder_placeholder(str(error.get("Key") or ""))
        )

    if transient is not None:
        raise transient
    return {"deleted": len(keys) - failed, "failed": failed, "failedFolders": failed_folders}


def changed_keys(bucket: str, expected: dict) -> set:
    """Heads every original and returns the ones that are not what the plan recorded.

    A key whose plan entry carries no tag is returned without being headed. A plan written before
    the tag was recorded, or edited since, cannot say which bytes the vault holds, and a missing
    tag read as "unchanged" would delete on a guess.

    Args:
      bucket: The source bucket.
      expected: Absolute key to the ETag the plan recorded for it, or None when it recorded none.

    Returns:
      The keys that must not be deleted: present with a different tag, headed with a fault that is
      not absence, or planned with no tag at all.

    Raises:
      TransientError: On a throttle or 5xx from any head, after the sweep has settled — a sweep
        that cannot see an original retries rather than concluding it is unchanged.
    """
    def changed(key: str) -> bool:
        """Reports whether one original differs from the plan's record of it.

        Args:
          key: The absolute source key.

        Returns:
          True when the original must be kept.

        Raises:
          TransientError: On a throttle or 5xx.
        """
        planned = expected[key]
        if not planned:
            return True
        try:
            head = clients.s3().head_object(Bucket=bucket, Key=key)
        except Exception as err:  # noqa: BLE001 - classified below
            errors.raise_if_transient(err, f"head {bucket}/{key}")
            return errors.error_code(err) not in _ABSENT_CODES
        return bool(head.get("ETag") != planned)

    keys = list(expected)
    with ThreadPoolExecutor(max_workers=SOURCE_HEAD_CONCURRENCY) as pool:
        return {key for key, kept in zip(keys, pool.map(changed, keys), strict=True) if kept}
